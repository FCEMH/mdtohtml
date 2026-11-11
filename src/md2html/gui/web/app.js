// MD2HTML Desktop Web Interface Logic

let currentMode = "folder"; // "file" | "folder" | "chatgpt"
let currentJobId = null;
let pollTimer = null;
let lastInspectData = null;
let lastReport = null;

// Per-mode settings state so title & output don't leak across tabs
const modeSettings = {
  folder: { title: "", output: "", inspectData: null },
  file: { title: "", output: "", inspectData: null },
  chatgpt: { title: "", output: "", inspectData: null },
};

// Dynamic catalog state for reordering & inclusion selection
let rawFiles = []; // [{ rel, name, title, size, mtime, parentParts }]
let fileOrder = []; // array of rel strings in current order
let isMergedMap = {}; // rel -> boolean (true: merge, false: skip)
let folderCollapsedMap = {}; // folderKey -> boolean

// ChatGPT share link session editing draft state
let chatgptSession = null;
// {
//   url: string,
//   title: string,
//   messages: [
//     { id, role, author_name, original_text, text, selected, modified }
//   ]
// }
let currentEditingMsgId = null;
let editorDebounceTimer = null;

// Fallback mock if opened in standalone browser for previewing layout
const api = {
  async check_environment() {
    return window.pywebview ? await window.pywebview.api.check_environment() : { status: "ready", gui_backend: "Mock Preview", risks: [] };
  },
  async load_settings() {
    return window.pywebview ? await window.pywebview.api.load_settings() : { theme: "auto", toc_depth: 3, search: true };
  },
  async save_settings(settings) {
    if (window.pywebview) await window.pywebview.api.save_settings(settings);
  },
  async choose_file(title, def) {
    return window.pywebview ? await window.pywebview.api.choose_file(title, def) : null;
  },
  async choose_folder(title, def) {
    return window.pywebview ? await window.pywebview.api.choose_folder(title, def) : null;
  },
  async choose_save_file(title, defName, defDir) {
    return window.pywebview ? await window.pywebview.api.choose_save_file(title, defName, defDir) : null;
  },
  async choose_save_markdown_file(title, defName, defDir) {
    return window.pywebview ? await window.pywebview.api.choose_save_markdown_file(title, defName, defDir) : null;
  },
  async render_markdown_preview(markdown) {
    return window.pywebview ? await window.pywebview.api.render_markdown_preview(markdown) : {
      success: true,
      html: `<div>${escapeHtml(markdown)}</div>`,
      full_html: `<!DOCTYPE html><html><body style="font-family:system-ui;padding:20px;line-height:1.7;"><div>${escapeHtml(markdown)}</div></body></html>`
    };
  },
  async preview_chat_messages(title, msgs) {
    return window.pywebview ? await window.pywebview.api.preview_chat_messages(title, msgs) : { success: false, error: "Native API not available" };
  },
  async save_markdown(targetPath, title, msgs) {
    return window.pywebview ? await window.pywebview.api.save_markdown(targetPath, title, msgs) : { success: false, error: "Native API not available" };
  },
  async inspect(type, path, opts) {
    return window.pywebview ? await window.pywebview.api.inspect(type, path, opts) : { success: false, error: "Native API not available in browser preview" };
  },
  async check_only(type, path, opts) {
    return window.pywebview ? await window.pywebview.api.check_only(type, path, opts) : { success: false, error: "Native API not available" };
  },
  async start_build(req) {
    return window.pywebview ? await window.pywebview.api.start_build(req) : { success: false, error: "Native API not available" };
  },
  async get_job_status(jid) {
    return window.pywebview ? await window.pywebview.api.get_job_status(jid) : { found: false };
  },
  async cancel_job(jid) {
    return window.pywebview ? await window.pywebview.api.cancel_job(jid) : { success: false };
  },
  async open_result(jid, action) {
    return window.pywebview ? await window.pywebview.api.open_result(jid, action) : { success: false };
  }
};

// Wait for pywebviewready
function init() {
  setupTabs();
  setupEventListeners();
  checkEnvironment();
  loadInitialSettings();
}

if (window.pywebview) {
  init();
} else {
  window.addEventListener("pywebviewready", init);
}

// Check if ChatGPT session has unsaved modifications or filtered selection
function hasUnsavedChatChanges() {
  if (!chatgptSession || !chatgptSession.messages || chatgptSession.messages.length === 0) return false;
  const anyModified = chatgptSession.messages.some(m => m.modified);
  const anyUnselected = chatgptSession.messages.some(m => !m.selected);
  return anyModified || anyUnselected;
}

// Tabs
function setupTabs() {
  const tabs = document.querySelectorAll(".segment-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      if (tab.dataset.mode === currentMode) return;

      if (currentMode === "chatgpt" && tab.dataset.mode !== "chatgpt" && hasUnsavedChatChanges()) {
        const confirmSwitch = confirm("当前分享内容已有修改或筛选尚未另存为 Markdown。切换来源将放弃这些修改。\n\n是否继续切换？（如需保留，请先取消并点击“另存 Markdown”）");
        if (!confirmSwitch) return;
      }

      // Preserve current mode's doc-title and output-path before switching
      if (modeSettings[currentMode]) {
        modeSettings[currentMode].title = document.getElementById("doc-title").value;
        modeSettings[currentMode].output = document.getElementById("output-path").value;
      }

      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentMode = tab.dataset.mode;

      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      document.getElementById(`pane-${currentMode}`).classList.add("active");

      // Update right preview header, toolbar and sort controls
      const previewTitle = document.querySelector(".preview-title");
      const sortControls = document.getElementById("sort-controls");
      const sortTip = document.getElementById("sort-tip");
      const chatgptToolbar = document.getElementById("chatgpt-toolbar");

      if (currentMode === "chatgpt") {
        previewTitle.textContent = "分享消息列表";
        document.getElementById("tree-footer-note").textContent = "提取的消息将按顺序合并整理为一个离线 HTML。";
        sortControls.style.display = "none";
        sortTip.style.display = "none";
        if (chatgptToolbar) chatgptToolbar.style.display = "flex";
      } else if (currentMode === "file") {
        previewTitle.textContent = "单文件信息";
        document.getElementById("tree-footer-note").textContent = "只收录该 Markdown 及其引用的资源。";
        sortControls.style.display = "none";
        sortTip.style.display = "none";
        if (chatgptToolbar) chatgptToolbar.style.display = "none";
      } else {
        previewTitle.textContent = "内容目录";
        document.getElementById("tree-footer-note").textContent = "图片将随 HTML 保存；目录中的顺序即输出顺序。";
        sortControls.style.display = "flex";
        sortTip.style.display = "inline";
        if (chatgptToolbar) chatgptToolbar.style.display = "none";
      }

      // Switch generation settings to active mode's stored content
      document.getElementById("doc-title").value = modeSettings[currentMode]?.title || "";
      document.getElementById("output-path").value = modeSettings[currentMode]?.output || "";

      setActionState("idle");
      triggerInspect();
    });
  });
}

// Event Listeners
function setupEventListeners() {
  // Folder browsing
  document.getElementById("btn-browse-folder").addEventListener("click", async () => {
    const cur = document.getElementById("folder-path").value.trim();
    const folder = await api.choose_folder("选择笔记文件夹", cur);
    if (folder) {
      document.getElementById("folder-path").value = folder;
      if (modeSettings.folder) {
        modeSettings.folder.title = "";
        modeSettings.folder.output = "";
        modeSettings.folder.inspectData = null;
      }
      setActionState("idle");
      triggerInspect();
    }
  });

  document.getElementById("folder-path").addEventListener("change", () => {
    if (modeSettings.folder) {
      modeSettings.folder.title = "";
      modeSettings.folder.output = "";
      modeSettings.folder.inspectData = null;
    }
    setActionState("idle");
    triggerInspect();
  });

  // File browsing
  document.getElementById("btn-browse-file").addEventListener("click", async () => {
    const cur = document.getElementById("file-path").value.trim();
    const file = await api.choose_file("选择 Markdown 文件", cur);
    if (file) {
      document.getElementById("file-path").value = file;
      if (modeSettings.file) {
        modeSettings.file.title = "";
        modeSettings.file.output = "";
        modeSettings.file.inspectData = null;
      }
      setActionState("idle");
      triggerInspect();
    }
  });

  document.getElementById("file-path").addEventListener("change", () => {
    if (modeSettings.file) {
      modeSettings.file.title = "";
      modeSettings.file.output = "";
      modeSettings.file.inspectData = null;
    }
    setActionState("idle");
    triggerInspect();
  });

  // Resource root browsing
  document.getElementById("btn-browse-res-root").addEventListener("click", async () => {
    const cur = document.getElementById("file-res-root").value.trim();
    const folder = await api.choose_folder("选择资源根目录", cur);
    if (folder) {
      document.getElementById("file-res-root").value = folder;
      triggerInspect();
    }
  });

  // Save As
  document.getElementById("btn-save-as").addEventListener("click", async () => {
    const curOut = document.getElementById("output-path").value.trim();
    let defName = "textbook.html";
    let defDir = "";
    if (curOut) {
      const parts = curOut.split("/");
      defName = parts[parts.length - 1] || "textbook.html";
      defDir = parts.slice(0, -1).join("/");
    }
    const saved = await api.choose_save_file("另存为 HTML", defName, defDir);
    if (saved) {
      document.getElementById("output-path").value = saved;
      if (modeSettings[currentMode]) {
        modeSettings[currentMode].output = saved;
      }
    }
  });

  // ChatGPT Fetch
  document.getElementById("btn-fetch-chatgpt").addEventListener("click", () => {
    if (modeSettings.chatgpt) {
      modeSettings.chatgpt.title = "";
      modeSettings.chatgpt.output = "";
      modeSettings.chatgpt.inspectData = null;
    }
    triggerInspect();
  });

  // Keep modeSettings in sync when user edits doc-title or output-path
  document.getElementById("doc-title").addEventListener("input", (e) => {
    if (modeSettings[currentMode]) {
      modeSettings[currentMode].title = e.target.value;
    }
  });
  document.getElementById("output-path").addEventListener("input", (e) => {
    if (modeSettings[currentMode]) {
      modeSettings[currentMode].output = e.target.value;
    }
  });

  // ChatGPT Toolbar buttons
  const btnChatSelectAll = document.getElementById("btn-chat-select-all");
  if (btnChatSelectAll) {
    btnChatSelectAll.addEventListener("click", () => {
      if (!chatgptSession) return;
      chatgptSession.messages.forEach(m => m.selected = true);
      renderCatalogTree();
    });
  }

  const btnChatDeselectAll = document.getElementById("btn-chat-deselect-all");
  if (btnChatDeselectAll) {
    btnChatDeselectAll.addEventListener("click", () => {
      if (!chatgptSession) return;
      chatgptSession.messages.forEach(m => m.selected = false);
      renderCatalogTree();
    });
  }

  const btnChatSelectAi = document.getElementById("btn-chat-select-ai");
  if (btnChatSelectAi) {
    btnChatSelectAi.addEventListener("click", () => {
      if (!chatgptSession) return;
      chatgptSession.messages.forEach(m => {
        m.selected = (m.role === "assistant");
      });
      renderCatalogTree();
    });
  }

  const btnChatPreviewMerged = document.getElementById("btn-chat-preview-merged");
  if (btnChatPreviewMerged) {
    btnChatPreviewMerged.addEventListener("click", () => {
      handlePreviewMerged();
    });
  }

  const btnChatSaveMd = document.getElementById("btn-chat-save-markdown");
  if (btnChatSaveMd) {
    btnChatSaveMd.addEventListener("click", () => {
      handleSaveMarkdown();
    });
  }

  // Rescan
  document.getElementById("btn-rescan").addEventListener("click", () => {
    setActionState("idle");
    triggerInspect();
  });

  // Select All / Deselect All header button click
  const colMergeHeader = document.getElementById("col-header-merge");
  if (colMergeHeader) {
    colMergeHeader.addEventListener("click", () => {
      if (currentMode === "chatgpt") {
        if (!chatgptSession || chatgptSession.messages.length === 0) return;
        const anySelected = chatgptSession.messages.some(m => m.selected);
        const nextVal = !anySelected;
        chatgptSession.messages.forEach(m => m.selected = nextVal);
        renderCatalogTree();
        return;
      }
      if (rawFiles.length === 0) return;
      const anyMerged = rawFiles.some(f => isMergedMap[f.rel] !== false);
      const nextVal = !anyMerged; // if some/all are merged, deselect all; if none merged, select all
      rawFiles.forEach(f => {
        isMergedMap[f.rel] = nextVal;
      });
      updateFolderSummaryMeta();
      renderCatalogTree();
    });
  }

  // Sort dropdown
  document.getElementById("sort-select").addEventListener("change", (e) => {
    handleSortChange(e.target.value);
  });

  // Advanced settings toggle
  document.getElementById("btn-toggle-advanced").addEventListener("click", () => {
    const drawer = document.getElementById("advanced-drawer");
    const isHidden = drawer.style.display === "none";
    drawer.style.display = isHidden ? "block" : "none";
    document.getElementById("btn-toggle-advanced").textContent = isHidden ? "高级设置 ∨" : "高级设置 >";
  });

  // Config browsing
  document.getElementById("btn-browse-config").addEventListener("click", async () => {
    const cur = document.getElementById("config-path").value.trim();
    const file = await api.choose_file("选择配置文件 (md2html.yml)", cur);
    if (file) {
      document.getElementById("config-path").value = file;
      triggerInspect();
    }
  });

  // Environment check badge click
  document.getElementById("btn-env-check").addEventListener("click", async () => {
    const env = await api.check_environment();
    showEnvModal(env);
  });

  // Check Content button
  document.getElementById("btn-check-content").addEventListener("click", () => {
    handleCheckContent();
  });

  // Build button
  document.getElementById("btn-build").addEventListener("click", () => {
    handleStartBuild();
  });

  // Cancel button
  document.getElementById("btn-cancel").addEventListener("click", () => {
    handleCancelBuild();
  });

  // Finished action buttons
  document.getElementById("btn-open-html").addEventListener("click", () => {
    if (currentJobId) api.open_result(currentJobId, "file");
  });
  document.getElementById("btn-open-folder").addEventListener("click", () => {
    if (currentJobId) api.open_result(currentJobId, "folder");
  });
  document.getElementById("btn-view-diag").addEventListener("click", () => {
    showDiagnosticsModal();
  });

  // Diagnostic Modal close
  document.getElementById("btn-close-modal").addEventListener("click", closeModal);
  document.getElementById("btn-modal-ok").addEventListener("click", closeModal);

  // Message Editor Modal listeners
  const btnCloseEditor = document.getElementById("btn-close-editor");
  if (btnCloseEditor) btnCloseEditor.addEventListener("click", closeMessageEditor);
  const btnEditorCancel = document.getElementById("btn-editor-cancel");
  if (btnEditorCancel) btnEditorCancel.addEventListener("click", closeMessageEditor);
  const btnEditorRestore = document.getElementById("btn-editor-restore");
  if (btnEditorRestore) btnEditorRestore.addEventListener("click", handleEditorRestore);
  const btnEditorApply = document.getElementById("btn-editor-apply");
  if (btnEditorApply) btnEditorApply.addEventListener("click", handleEditorApply);
  const editorTextarea = document.getElementById("editor-textarea");
  if (editorTextarea) editorTextarea.addEventListener("input", handleEditorInput);

  // Merged Preview Modal listeners
  const btnCloseMerged = document.getElementById("btn-close-merged-preview");
  if (btnCloseMerged) btnCloseMerged.addEventListener("click", closeMergedPreview);
  const btnMergedClose = document.getElementById("btn-merged-close");
  if (btnMergedClose) btnMergedClose.addEventListener("click", closeMergedPreview);
  const btnMergedSave = document.getElementById("btn-merged-save-md");
  if (btnMergedSave) btnMergedSave.addEventListener("click", () => {
    closeMergedPreview();
    handleSaveMarkdown();
  });
  const btnMergedBuild = document.getElementById("btn-merged-build");
  if (btnMergedBuild) btnMergedBuild.addEventListener("click", () => {
    closeMergedPreview();
    handleStartBuild();
  });
}

// Environment Check
async function checkEnvironment() {
  try {
    const res = await api.check_environment();
    const badge = document.getElementById("btn-env-check");
    const text = document.getElementById("env-status-text");

    badge.className = "env-badge";
    if (res.status === "ready") {
      badge.classList.add("ready");
      text.textContent = "环境检查：就绪";
    } else if (res.status === "warning") {
      badge.classList.add("warning");
      text.textContent = "环境检查：部分依赖警报";
    } else {
      badge.classList.add("error");
      text.textContent = "环境检查：依赖缺失";
    }
  } catch (e) {
    console.error("Environment check failed:", e);
  }
}

// Initial Settings
async function loadInitialSettings() {
  try {
    const s = await api.load_settings();
    const themeSelect = document.getElementById("theme-select");
    if (themeSelect && s.theme) themeSelect.value = s.theme;
    if (s.toc_depth) document.getElementById("toc-depth-select").value = s.toc_depth;
    if (s.search !== undefined) document.getElementById("search-enabled").checked = s.search;
  } catch (e) {
    console.error("Settings load failed:", e);
  }
}

// Flatten tree nodes to extract all file entries
function extractFilesFromTree(nodes, parentParts = []) {
  let files = [];
  nodes.forEach(node => {
    if (node.type === "file") {
      files.push({
        rel: node.rel,
        name: node.name,
        title: node.title,
        size: node.size || 0,
        mtime: node.mtime || 0,
        parentParts: parentParts,
      });
    } else if (node.type === "dir" && node.children) {
      files = files.concat(extractFilesFromTree(node.children, [...parentParts, node.name]));
    }
  });
  return files;
}

// Collect current request parameters
function getRequestParameters() {
  let sourcePathOrUrl = "";
  let sourceData = {};

  if (currentMode === "folder") {
    sourcePathOrUrl = document.getElementById("folder-path").value.trim();
    // Gather selected files in current order
    const selectedFiles = fileOrder.filter(rel => isMergedMap[rel] !== false);
    sourceData = {
      root: sourcePathOrUrl,
      recursive: true,
      include_files: selectedFiles.length > 0 ? selectedFiles : null,
    };
  } else if (currentMode === "file") {
    sourcePathOrUrl = document.getElementById("file-path").value.trim();
    const resRoot = document.getElementById("file-res-root").value.trim();
    const forceInc = document.getElementById("file-force-include").checked;
    sourceData = {
      path: sourcePathOrUrl,
      resource_root: resRoot || null,
      explicitly_include: forceInc,
    };
  } else if (currentMode === "chatgpt") {
    sourcePathOrUrl = document.getElementById("chatgpt-url").value.trim();
    const selectedMsgs = (chatgptSession && chatgptSession.messages)
      ? chatgptSession.messages.filter(m => m.selected)
      : [];
    sourceData = {
      url: sourcePathOrUrl,
      title: document.getElementById("doc-title").value.trim() || (chatgptSession ? chatgptSession.title : ""),
      messages: selectedMsgs.map(m => ({
        id: m.id,
        role: m.role,
        author_name: m.author_name,
        text: m.text,
      })),
    };
  }

  const output = document.getElementById("output-path").value.trim();
  const title = document.getElementById("doc-title").value.trim();
  const themeSelect = document.getElementById("theme-select");
  const theme = themeSelect ? themeSelect.value : "auto";
  const tocDepth = parseInt(document.getElementById("toc-depth-select").value, 10);
  const search = document.getElementById("search-enabled").checked;
  const strict = document.getElementById("strict-mode").checked;
  const skipDraft = document.getElementById("skip-draft").checked;
  const configPath = document.getElementById("config-path").value.trim() || null;

  const overrides = {
    "render.theme": theme,
    "render.toc_depth": tocDepth,
    "render.search": search,
    "render.strict": strict,
    "content.skip_draft": skipDraft,
  };
  if (title) {
    overrides["book.title"] = title;
  }

  return {
    source_type: currentMode,
    source_path_or_url: sourcePathOrUrl,
    source_data: sourceData,
    output: output || null,
    config_path: configPath,
    overrides: overrides,
  };
}

// Trigger inspect
async function triggerInspect() {
  setActionState("idle");
  const req = getRequestParameters();
  if (!req.source_path_or_url) {
    renderEmptyState();
    return;
  }

  if (req.source_type === "chatgpt" && hasUnsavedChatChanges()) {
    const confirmReinspect = confirm("当前分享内容已有修改或筛选尚未另存为 Markdown。重新读取将放弃这些修改。\n\n是否继续重新读取？（如需保留，请先取消并点击“另存 Markdown”）");
    if (!confirmReinspect) {
      setActionState("idle");
      return;
    }
  }

  updateStatus("reading", "正在读取来源内容...");
  const treeContainer = document.getElementById("tree-container");
  treeContainer.innerHTML = `<div class="empty-state"><p>正在扫描并解析来源...</p></div>`;

  try {
    const res = await api.inspect(req.source_type, req.source_path_or_url, {
      resource_root: req.source_data.resource_root,
      config_path: req.config_path,
      overrides: req.overrides,
    });

    if (!res.success) {
      setActionState("idle");
      updateStatus("error", `读取失败: ${res.error}`);
      if (req.source_type === "chatgpt" && chatgptSession && chatgptSession.messages && chatgptSession.messages.length > 0) {
        renderCatalogTree();
        alert(`读取新内容失败: ${res.error}\n已保留当前编辑稿。`);
      } else {
        treeContainer.innerHTML = `<div class="empty-state" style="color:var(--danger-color)"><p>⚠️ ${escapeHtml(res.error)}</p></div>`;
        document.getElementById("summary-meta").textContent = "扫描遇到错误";
      }
      return;
    }

    lastInspectData = res.data;

    // Reset and initialize files state
    if (res.data.type === "folder") {
      rawFiles = extractFilesFromTree(res.data.tree);
      fileOrder = rawFiles.map(f => f.rel);
      isMergedMap = {};
      rawFiles.forEach(f => {
        isMergedMap[f.rel] = true;
      });
      document.getElementById("sort-select").value = "default";
    } else if (res.data.type === "chatgpt") {
      chatgptSession = {
        url: res.data.url,
        title: res.data.title || "ChatGPT 分享内容",
        messages: (res.data.tree || []).map((m, idx) => ({
          id: m.id || `msg-${idx + 1}`,
          role: m.role || "unknown",
          author_name: m.author_name || null,
          original_text: m.text || "",
          text: m.text || "",
          selected: true,
          modified: false,
        })),
      };
    }

    renderInspectResult(res.data);
    setActionState("idle");
    updateStatus("ready", "生成进度将在此显示，诊断信息可展开查看。");
  } catch (e) {
    setActionState("idle");
    updateStatus("error", `扫描出错: ${e}`);
  }
}

// Hierarchical Tree Sorting (Folders First, then Files, recursively)
function sortHierarchically(files, sortType) {
  function makeTree(fileList) {
    const root = { name: "", isDir: true, dirs: new Map(), files: [] };
    fileList.forEach(file => {
      let cur = root;
      file.parentParts.forEach(p => {
        if (!cur.dirs.has(p)) {
          cur.dirs.set(p, { name: p, isDir: true, dirs: new Map(), files: [] });
        }
        cur = cur.dirs.get(p);
      });
      cur.files.push(file);
    });
    return root;
  }

  const root = makeTree(files);

  function computeAggregates(node) {
    let size = node.files.reduce((s, f) => s + (f.size || 0), 0);
    let mtimes = node.files.map(f => f.mtime || 0);
    for (const sub of node.dirs.values()) {
      computeAggregates(sub);
      size += sub.totalSize;
      if (sub.maxMtime > 0) mtimes.push(sub.maxMtime);
    }
    node.totalSize = size;
    node.maxMtime = mtimes.length > 0 ? Math.max(...mtimes) : 0;
    node.minMtime = mtimes.length > 0 ? Math.min(...mtimes) : 0;
  }
  computeAggregates(root);

  function compareItems(a, b, isDir) {
    if (sortType === "name-asc") {
      return a.name.localeCompare(b.name, "zh", { numeric: true });
    } else if (sortType === "name-desc") {
      return b.name.localeCompare(a.name, "zh", { numeric: true });
    } else if (sortType === "time-desc") {
      const timeA = isDir ? a.maxMtime : a.mtime;
      const timeB = isDir ? b.maxMtime : b.mtime;
      return (timeB || 0) - (timeA || 0);
    } else if (sortType === "time-asc") {
      const timeA = isDir ? a.minMtime : a.mtime;
      const timeB = isDir ? b.minMtime : b.mtime;
      return (timeA || 0) - (timeB || 0);
    } else if (sortType === "size-desc") {
      const sizeA = isDir ? a.totalSize : a.size;
      const sizeB = isDir ? b.totalSize : b.size;
      return (sizeB || 0) - (sizeA || 0);
    } else if (sortType === "size-asc") {
      const sizeA = isDir ? a.totalSize : a.size;
      const sizeB = isDir ? b.totalSize : b.size;
      return (sizeA || 0) - (sizeB || 0);
    } else {
      // default: preserve initial scan order
      const idxA = files.findIndex(f => isDir ? (f.rel.startsWith(a.name + "/") || f.parentParts.includes(a.name)) : f.rel === a.rel);
      const idxB = files.findIndex(f => isDir ? (f.rel.startsWith(b.name + "/") || f.parentParts.includes(b.name)) : f.rel === b.rel);
      return idxA - idxB;
    }
  }

  const resultFiles = [];
  function traverse(node) {
    const dirList = Array.from(node.dirs.values());
    const fileList = [...node.files];

    dirList.sort((a, b) => compareItems(a, b, true));
    fileList.sort((a, b) => compareItems(a, b, false));

    // Folders on top: directories first, then files
    dirList.forEach(d => traverse(d));
    fileList.forEach(f => resultFiles.push(f));
  }

  traverse(root);
  return resultFiles;
}

// Sorting logic
function handleSortChange(sortType) {
  if (currentMode !== "folder" || rawFiles.length === 0) return;

  const sortedFiles = sortHierarchically(rawFiles, sortType);
  fileOrder = sortedFiles.map(f => f.rel);
  renderCatalogTree();
}

// Render Inspect Result
function renderInspectResult(data) {
  const titleInput = document.getElementById("doc-title");
  const outputInput = document.getElementById("output-path");

  if (data.type === "chatgpt") {
    const defaultTitle = data.title || "ChatGPT 分享内容";
    const safeName = defaultTitle.replace(/[\\/*?:"<>|]/g, "_").trim() || "chatgpt";
    const defaultOutput = `${safeName}.html`;

    titleInput.value = modeSettings.chatgpt?.title || defaultTitle;
    outputInput.value = modeSettings.chatgpt?.output || defaultOutput;
    if (modeSettings.chatgpt) {
      modeSettings.chatgpt.title = titleInput.value;
      modeSettings.chatgpt.output = outputInput.value;
      modeSettings.chatgpt.inspectData = data;
    }
  } else {
    titleInput.value = modeSettings[data.type]?.title || data.title || "";
    outputInput.value = modeSettings[data.type]?.output || data.suggested_output || "";
    if (modeSettings[data.type]) {
      modeSettings[data.type].title = titleInput.value;
      modeSettings[data.type].output = outputInput.value;
      modeSettings[data.type].inspectData = data;
    }
  }

  renderCatalogTree();
}

// Render the tree based on current state
function renderCatalogTree() {
  if (!lastInspectData) return;
  const data = lastInspectData;

  const metaEl = document.getElementById("summary-meta");
  const treeContainer = document.getElementById("tree-container");
  treeContainer.innerHTML = "";

  if (data.type === "chatgpt") {
    if (!chatgptSession) {
      chatgptSession = {
        url: data.url || "",
        title: data.title || "ChatGPT 分享内容",
        messages: (data.tree || []).map((m, idx) => ({
          id: m.id || `msg-${idx + 1}`,
          role: m.role || "unknown",
          author_name: m.author_name || null,
          original_text: m.text || "",
          text: m.text || "",
          selected: true,
          modified: false,
        })),
      };
    }

    const messages = chatgptSession.messages;
    const total = messages.length;
    const selectedList = messages.filter(m => m.selected);
    const selectedCount = selectedList.length;
    const assistantCount = messages.filter(m => m.role === "assistant").length;
    const userCount = messages.filter(m => m.role === "user").length;
    const totalChars = selectedList.reduce((sum, m) => sum + m.text.length, 0);

    metaEl.innerHTML = `共 <strong>${total}</strong> 条消息 (${assistantCount} 条AI回答, ${userCount} 条提问) · 已选 <strong style="color:var(--primary-color)">${selectedCount}</strong> 条 · 约 <strong>${totalChars.toLocaleString()}</strong> 字符`;

    // Disable build/check if 0 selected
    const buildBtn = document.getElementById("btn-build");
    const checkBtn = document.getElementById("btn-check-content");
    if (selectedCount === 0) {
      buildBtn.disabled = true;
      checkBtn.disabled = true;
      buildBtn.title = "请至少勾选一条要收录的消息";
    } else {
      buildBtn.disabled = false;
      checkBtn.disabled = false;
      buildBtn.title = "";
    }

    if (messages.length === 0) {
      treeContainer.innerHTML = `<div class="empty-state"><p>未在分享链接中发现任何消息</p></div>`;
      return;
    }

    messages.forEach((m, idx) => {
      const itemEl = document.createElement("div");
      itemEl.className = `chat-message-item ${m.selected ? 'selected' : ''}`;
      itemEl.dataset.id = m.id;

      const roleName = m.role === 'assistant' ? 'AI 助手' : (m.role === 'user' ? '用户' : (m.role === 'system' ? '系统' : m.role));
      const snippet = m.text ? m.text.slice(0, 160).trim() : '（无内容）';

      itemEl.innerHTML = `
        <div class="chat-message-header">
          <label class="chat-checkbox-label" title="勾选以收录本条消息">
            <input type="checkbox" class="chat-msg-checkbox" data-id="${escapeHtml(m.id)}" ${m.selected ? 'checked' : ''}>
            <span class="role-badge role-${escapeHtml(m.role)}">消息 ${idx + 1} · ${escapeHtml(roleName)}</span>
            ${m.author_name ? `<span class="author-name">(${escapeHtml(m.author_name)})</span>` : ''}
            ${m.modified ? `<span class="modified-badge">已修改</span>` : ''}
          </label>
          <div class="chat-msg-actions">
            <span class="chat-msg-chars">${m.text.length.toLocaleString()} 字符</span>
            <button type="button" class="btn btn-xs btn-outline btn-edit-msg" data-id="${escapeHtml(m.id)}">查看 / 编辑</button>
          </div>
        </div>
        <div class="chat-message-snippet">${escapeHtml(snippet)}</div>
      `;

      // Checkbox event
      const cb = itemEl.querySelector(".chat-msg-checkbox");
      cb.addEventListener("change", (e) => {
        m.selected = e.target.checked;
        if (m.selected) {
          itemEl.classList.add("selected");
        } else {
          itemEl.classList.remove("selected");
        }
        updateChatSummaryMeta();
      });

      // Edit button event
      const editBtn = itemEl.querySelector(".btn-edit-msg");
      editBtn.addEventListener("click", () => {
        openMessageEditor(m.id);
      });

      treeContainer.appendChild(itemEl);
    });
  } else if (data.type === "file") {
    metaEl.textContent = `单文件 · 1 篇笔记 · 最终输出 1 个 HTML`;
    const doc = data.tree[0];
    const node = document.createElement("div");
    node.className = "tree-file";
    node.innerHTML = `
      <span class="file-icon">📄</span>
      <div class="file-title-wrap">
        <span class="file-title">${escapeHtml(data.title || doc.name)}</span>
        <span class="file-size">${formatBytes(doc.size)}</span>
      </div>
      <button type="button" class="circle-toggle active" title="已选择收录"></button>
    `;
    treeContainer.appendChild(node);
  } else {
    // Folder mode: dynamic ordered rendering
    updateFolderSummaryMeta();

    // Reconstruct tree hierarchy in the exact order of fileOrder
    const orderedFiles = fileOrder.map(rel => rawFiles.find(f => f.rel === rel)).filter(Boolean);
    const dynamicTree = buildHierarchicalTree(orderedFiles);

    const rootFragment = document.createDocumentFragment();
    renderDynamicTreeNodes(dynamicTree, rootFragment);
    treeContainer.appendChild(rootFragment);
  }
}

// Build hierarchical structure from ordered files list
function buildHierarchicalTree(files) {
  const root = { type: "dir", name: "", children: [] };

  files.forEach(file => {
    let current = root;
    file.parentParts.forEach((part, idx) => {
      const folderKey = file.parentParts.slice(0, idx + 1).join("/");
      let foundDir = current.children.find(c => c.type === "dir" && c.folderKey === folderKey);
      if (!foundDir) {
        foundDir = {
          type: "dir",
          name: part,
          folderKey: folderKey,
          children: [],
          allRels: [],
        };
        current.children.push(foundDir);
      }
      foundDir.allRels.push(file.rel);
      current = foundDir;
    });

    current.children.push({
      type: "file",
      rel: file.rel,
      name: file.name,
      title: file.title,
      size: file.size,
      mtime: file.mtime,
    });
  });

  return root.children;
}

// Render dynamic tree nodes with drag & drop and circular toggle
function renderDynamicTreeNodes(nodes, container) {
  nodes.forEach(item => {
    const nodeEl = document.createElement("div");
    nodeEl.className = "tree-node";

    if (item.type === "dir") {
      const folderKey = item.folderKey;
      const isCollapsed = Boolean(folderCollapsedMap[folderKey]);

      // Count merged child files
      const totalInFolder = item.allRels.length;
      const mergedInFolder = item.allRels.filter(r => isMergedMap[r] !== false).length;
      const allMerged = mergedInFolder === totalInFolder && totalInFolder > 0;
      const partialMerged = mergedInFolder > 0 && mergedInFolder < totalInFolder;

      let circleClass = "";
      if (allMerged) {
        circleClass = "active";
      } else if (partialMerged) {
        circleClass = "partial";
      }

      const folderHeader = document.createElement("div");
      folderHeader.className = "tree-folder";
      folderHeader.setAttribute("draggable", "true");
      folderHeader.dataset.type = "dir";
      folderHeader.dataset.folderKey = folderKey;

      folderHeader.innerHTML = `
        <span class="drag-handle" title="按住可拖拽整个目录排序">⠿</span>
        <span class="tree-arrow ${isCollapsed ? 'collapsed' : ''}">▼</span>
        <span>📁</span>
        <span style="flex:1;">${escapeHtml(item.name)} <span style="font-size:11px; font-weight:normal; color:#94a3b8;">(${mergedInFolder}/${totalInFolder})</span></span>
        <button type="button" class="circle-toggle folder-circle-toggle ${circleClass}" title="切换本目录下所有文件是否合并"></button>
      `;

      // Folder collapse toggle
      folderHeader.addEventListener("click", (e) => {
        if (e.target.closest(".circle-toggle") || e.target.closest(".drag-handle")) return;
        const nowCollapsed = !folderCollapsedMap[folderKey];
        folderCollapsedMap[folderKey] = nowCollapsed;
        renderCatalogTree();
      });

      // Folder batch merge circular toggle
      const mergeBtn = folderHeader.querySelector(".folder-circle-toggle");
      mergeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const nextState = !allMerged; // if all merged, turn all off; otherwise turn all on
        item.allRels.forEach(r => {
          isMergedMap[r] = nextState;
        });
        updateFolderSummaryMeta();
        renderCatalogTree();
      });

      // Setup drag and drop for folder
      setupUnifiedDragAndDrop(folderHeader, {
        type: "dir",
        folderKey: folderKey,
        rels: item.allRels,
      });

      const childrenContainer = document.createElement("div");
      childrenContainer.className = `tree-children ${isCollapsed ? 'collapsed' : ''}`;
      renderDynamicTreeNodes(item.children, childrenContainer);

      nodeEl.appendChild(folderHeader);
      nodeEl.appendChild(childrenContainer);
    } else {
      // File node
      const isMerged = isMergedMap[item.rel] !== false;

      const fileEl = document.createElement("div");
      fileEl.className = `tree-file ${isMerged ? '' : 'skipped'}`;
      fileEl.setAttribute("draggable", "true");
      fileEl.dataset.type = "file";
      fileEl.dataset.rel = item.rel;

      fileEl.innerHTML = `
        <span class="drag-handle" title="按住可拖拽排序">⠿</span>
        <span class="file-icon">📄</span>
        <div class="file-title-wrap">
          <span class="file-title" title="${escapeHtml(item.rel)}">${escapeHtml(item.title || item.name)}</span>
          <span class="file-size">${formatBytes(item.size)}</span>
        </div>
        <button type="button" class="circle-toggle file-circle-toggle ${isMerged ? 'active' : ''}" title="${isMerged ? '已选择合并（点击取消）' : '未选择合并（点击选择）'}"></button>
      `;

      // Single file merge circular toggle
      const choiceBtn = fileEl.querySelector(".file-circle-toggle");
      choiceBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        isMergedMap[item.rel] = !isMerged;
        updateFolderSummaryMeta();
        renderCatalogTree();
      });

      // Setup drag and drop for file
      setupUnifiedDragAndDrop(fileEl, {
        type: "file",
        rel: item.rel,
        rels: [item.rel],
      });

      nodeEl.appendChild(fileEl);
    }

    container.appendChild(nodeEl);
  });
}

// Unified Drag & Drop Setup (for both files and folders)
let activeDrag = null; // { type: 'file' | 'dir', rel?, folderKey?, rels: string[] }

function setupUnifiedDragAndDrop(element, itemData) {
  element.addEventListener("dragstart", (e) => {
    activeDrag = itemData;
    element.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", JSON.stringify(itemData));
  });

  element.addEventListener("dragend", () => {
    element.classList.remove("dragging");
    document.querySelectorAll(".tree-file, .tree-folder").forEach(el => {
      el.classList.remove("drag-over-top", "drag-over-bottom");
    });
    activeDrag = null;
  });

  element.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (!activeDrag) return;

    // Do not drop onto self or within own folder
    if (activeDrag.type === "file" && itemData.type === "file" && activeDrag.rel === itemData.rel) return;
    if (activeDrag.type === "dir" && itemData.type === "dir" && activeDrag.folderKey === itemData.folderKey) return;
    if (activeDrag.type === "dir" && itemData.type === "file" && activeDrag.rels.includes(itemData.rel)) return;

    e.dataTransfer.dropEffect = "move";
    const rect = element.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;

    if (e.clientY < midY) {
      element.classList.add("drag-over-top");
      element.classList.remove("drag-over-bottom");
    } else {
      element.classList.add("drag-over-bottom");
      element.classList.remove("drag-over-top");
    }
  });

  element.addEventListener("dragleave", () => {
    element.classList.remove("drag-over-top", "drag-over-bottom");
  });

  element.addEventListener("drop", (e) => {
    e.preventDefault();
    element.classList.remove("drag-over-top", "drag-over-bottom");

    if (!activeDrag) return;

    // Determine moving files
    const movingRels = activeDrag.rels;
    if (!movingRels || movingRels.length === 0) return;

    // Determine target anchor file
    let targetAnchorRel = null;
    const rect = element.getBoundingClientRect();
    const insertBefore = e.clientY < (rect.top + rect.height / 2);

    if (itemData.type === "file") {
      targetAnchorRel = itemData.rel;
    } else if (itemData.type === "dir") {
      const targetRels = itemData.rels;
      if (!targetRels || targetRels.length === 0) return;
      targetAnchorRel = insertBefore ? targetRels[0] : targetRels[targetRels.length - 1];
    }

    if (!targetAnchorRel || movingRels.includes(targetAnchorRel)) return;

    // Reorder fileOrder array
    // 1. Remove moving files from fileOrder
    const remaining = fileOrder.filter(r => !movingRels.includes(r));
    // 2. Find anchor index in remaining
    const anchorIdx = remaining.indexOf(targetAnchorRel);
    if (anchorIdx === -1) return;

    const insertIdx = insertBefore ? anchorIdx : anchorIdx + 1;
    remaining.splice(insertIdx, 0, ...movingRels);
    fileOrder = remaining;

    // Update sort dropdown to custom
    document.getElementById("sort-select").value = "custom";
    renderCatalogTree();
  });
}

// Update ChatGPT summary meta count
function updateChatSummaryMeta() {
  if (currentMode !== "chatgpt" || !chatgptSession) return;
  const messages = chatgptSession.messages;
  const total = messages.length;
  const selectedList = messages.filter(m => m.selected);
  const selectedCount = selectedList.length;
  const assistantCount = messages.filter(m => m.role === "assistant").length;
  const userCount = messages.filter(m => m.role === "user").length;
  const totalChars = selectedList.reduce((sum, m) => sum + m.text.length, 0);

  const metaEl = document.getElementById("summary-meta");
  metaEl.innerHTML = `共 <strong>${total}</strong> 条消息 (${assistantCount} 条AI回答, ${userCount} 条提问) · 已选 <strong style="color:var(--primary-color)">${selectedCount}</strong> 条 · 约 <strong>${totalChars.toLocaleString()}</strong> 字符`;

  const buildBtn = document.getElementById("btn-build");
  const checkBtn = document.getElementById("btn-check-content");
  if (selectedCount === 0) {
    buildBtn.disabled = true;
    checkBtn.disabled = true;
    buildBtn.title = "请至少勾选一条要收录的消息";
  } else {
    buildBtn.disabled = false;
    checkBtn.disabled = false;
    buildBtn.title = "";
  }
}

// Open Message View / Edit Modal
async function openMessageEditor(msgId) {
  if (!chatgptSession) return;
  const msg = chatgptSession.messages.find(m => m.id === msgId);
  if (!msg) return;

  currentEditingMsgId = msgId;
  const roleName = msg.role === 'assistant' ? 'AI 助手' : (msg.role === 'user' ? '用户' : (msg.role === 'system' ? '系统' : msg.role));
  const idx = chatgptSession.messages.indexOf(msg) + 1;
  document.getElementById("editor-modal-title").textContent = `查看 / 编辑消息 ${idx} · ${roleName}`;

  const textarea = document.getElementById("editor-textarea");
  textarea.value = msg.text;
  document.getElementById("editor-char-count").textContent = `${msg.text.length.toLocaleString()} 字符`;
  document.getElementById("editor-preview-status").textContent = "正在渲染预览...";

  const modal = document.getElementById("modal-msg-editor");
  modal.style.display = "flex";

  try {
    const res = await api.render_markdown_preview(msg.text);
    if (res.success && res.full_html) {
      document.getElementById("editor-preview-iframe").srcdoc = res.full_html;
      document.getElementById("editor-preview-status").textContent = "预览已同步";
    } else {
      document.getElementById("editor-preview-status").textContent = `渲染异常: ${res.error || "未知错误"}`;
    }
  } catch (e) {
    document.getElementById("editor-preview-status").textContent = `渲染出错: ${e}`;
  }
}

// Debounced input handler for message editor
function handleEditorInput() {
  const text = document.getElementById("editor-textarea").value;
  document.getElementById("editor-char-count").textContent = `${text.length.toLocaleString()} 字符`;
  document.getElementById("editor-preview-status").textContent = "正在渲染预览...";

  clearTimeout(editorDebounceTimer);
  editorDebounceTimer = setTimeout(async () => {
    try {
      const res = await api.render_markdown_preview(text);
      if (res.success && res.full_html) {
        document.getElementById("editor-preview-iframe").srcdoc = res.full_html;
        document.getElementById("editor-preview-status").textContent = "预览已同步";
      } else {
        document.getElementById("editor-preview-status").textContent = `渲染异常: ${res.error || "未知错误"}`;
      }
    } catch (e) {
      document.getElementById("editor-preview-status").textContent = `渲染出错: ${e}`;
    }
  }, 300);
}

// Restore original message text
function handleEditorRestore() {
  if (!chatgptSession || !currentEditingMsgId) return;
  const msg = chatgptSession.messages.find(m => m.id === currentEditingMsgId);
  if (!msg) return;
  document.getElementById("editor-textarea").value = msg.original_text;
  handleEditorInput();
}

// Apply edited message text
function handleEditorApply() {
  if (!chatgptSession || !currentEditingMsgId) return;
  const msg = chatgptSession.messages.find(m => m.id === currentEditingMsgId);
  if (!msg) return;

  const newText = document.getElementById("editor-textarea").value;
  msg.text = newText;
  msg.modified = (msg.text !== msg.original_text);

  closeMessageEditor();
  renderCatalogTree();
}

function closeMessageEditor() {
  clearTimeout(editorDebounceTimer);
  document.getElementById("modal-msg-editor").style.display = "none";
  currentEditingMsgId = null;
}

// Preview Merged Selected Content
async function handlePreviewMerged() {
  if (!chatgptSession) return;
  const selectedMsgs = chatgptSession.messages.filter(m => m.selected);
  if (selectedMsgs.length === 0) {
    alert("请至少勾选一条消息进行预览");
    return;
  }

  const title = document.getElementById("doc-title").value.trim() || chatgptSession.title || "AI分享内容";
  document.getElementById("merged-preview-title").textContent = `预览已选内容 (共 ${selectedMsgs.length} 条消息)`;

  const modal = document.getElementById("modal-merged-preview");
  modal.style.display = "flex";
  const iframe = document.getElementById("merged-preview-iframe");
  iframe.srcdoc = `<!DOCTYPE html><html><body style="font-family:system-ui;padding:40px;color:#64748b;text-align:center;">正在使用 Pandoc 与 KaTeX 渲染完整排版预览...</body></html>`;

  try {
    const res = await api.preview_chat_messages(title, selectedMsgs);
    if (res.success && res.full_html) {
      iframe.srcdoc = res.full_html;
    } else {
      iframe.srcdoc = `<!DOCTYPE html><html><body style="font-family:system-ui;padding:40px;color:#dc2626;text-align:center;">预览生成失败: ${escapeHtml(res.error || "未知错误")}</body></html>`;
    }
  } catch (e) {
    iframe.srcdoc = `<!DOCTYPE html><html><body style="font-family:system-ui;padding:40px;color:#dc2626;text-align:center;">预览生成出错: ${escapeHtml(String(e))}</body></html>`;
  }
}

function closeMergedPreview() {
  document.getElementById("modal-merged-preview").style.display = "none";
}

// Save Selected & Modified Content as Markdown
async function handleSaveMarkdown() {
  if (!chatgptSession) return;
  const selectedMsgs = chatgptSession.messages.filter(m => m.selected);
  if (selectedMsgs.length === 0) {
    alert("请至少勾选一条消息进行保存");
    return;
  }

  const title = document.getElementById("doc-title").value.trim() || chatgptSession.title || "AI分享内容";
  const safeName = title.replace(/[\\/*?:"<>|]/g, "_").trim() || "document";
  const defFilename = `${safeName}.md`;

  const targetPath = await api.choose_save_markdown_file("另存 Markdown", defFilename);
  if (!targetPath) return;

  updateStatus("running", "正在下载图片并保存 Markdown 文件...");
  try {
    const res = await api.save_markdown(targetPath, title, selectedMsgs);
    if (res.success) {
      updateStatus("ready", `Markdown 已另存至: ${res.path}`);
      alert(`Markdown 文件已成功保存至:\n${res.path}\n\n配套图片保存在 images/ 相对目录。\n后续可以通过“单个文件”模式直接转换该 Markdown。`);
    } else {
      updateStatus("error", `保存失败: ${res.error}`);
      alert(`保存 Markdown 失败: ${res.error}`);
    }
  } catch (e) {
    updateStatus("error", `保存出错: ${e}`);
    alert(`保存 Markdown 出错: ${e}`);
  }
}

// Update summary meta count
function updateFolderSummaryMeta() {
  if (currentMode !== "folder") return;

  const total = rawFiles.length;
  const selectedCount = fileOrder.filter(r => isMergedMap[r] !== false).length;
  const directories = lastInspectData ? lastInspectData.stats.directories : 1;

  const metaEl = document.getElementById("summary-meta");
  metaEl.innerHTML = `共 <strong>${total}</strong> 篇笔记 · 已选 <strong style="color:var(--primary-color)">${selectedCount}</strong> 篇 · ${directories} 层目录 · 合并输出 1 个 HTML`;

  // Disable build if 0 files selected
  const buildBtn = document.getElementById("btn-build");
  const checkBtn = document.getElementById("btn-check-content");
  if (selectedCount === 0) {
    buildBtn.disabled = true;
    checkBtn.disabled = true;
    buildBtn.title = "请至少勾选一个要合并的文件";
  } else {
    buildBtn.disabled = false;
    checkBtn.disabled = false;
    buildBtn.title = "";
  }
}

function renderEmptyState() {
  lastInspectData = null;
  if (modeSettings[currentMode]) {
    modeSettings[currentMode].inspectData = null;
    modeSettings[currentMode].title = "";
    modeSettings[currentMode].output = "";
  }
  document.getElementById("doc-title").value = "";
  document.getElementById("output-path").value = "";
  setActionState("idle");
  updateStatus("ready", "生成进度将在此显示，诊断信息可展开查看。");
  document.getElementById("summary-meta").textContent = "尚未选择输入来源";
  document.getElementById("tree-container").innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">📁</div>
      <p>请在左侧选择文件、文件夹或输入 AI 分享链接</p>
    </div>
  `;
}

// Dry-run Check Content
async function handleCheckContent() {
  const req = getRequestParameters();
  if (!req.source_path_or_url) {
    alert("请先选择或输入内容来源");
    return;
  }
  if (currentMode === "folder" && (!req.source_data.include_files || req.source_data.include_files.length === 0)) {
    alert("请至少选择一个要合并的 Markdown 文件");
    return;
  }
  if (currentMode === "chatgpt" && (!req.source_data.messages || req.source_data.messages.length === 0)) {
    alert("请至少勾选一条要收录的消息");
    return;
  }

  updateStatus("running", "正在进行完整内容与完整性检查...");
  document.getElementById("btn-check-content").disabled = true;

  try {
    const res = await api.check_only(req.source_type, req.source_path_or_url, {
      resource_root: req.source_data.resource_root,
      include_files: req.source_data.include_files,
      messages: req.source_data.messages,
      title: req.source_data.title,
      config_path: req.config_path,
      overrides: req.overrides,
    });

    document.getElementById("btn-check-content").disabled = false;

    if (!res.success) {
      updateStatus("error", `检查失败: ${res.error}`);
      showModal("检查失败", `<div class="diag-item error"><div class="diag-title">构建检查未通过</div><p>${escapeHtml(res.error)}</p></div>`);
      return;
    }

    lastReport = res.data.report;
    const issues = lastReport.issues || [];
    const errors = issues.filter(i => i.severity === "error").length;
    const warnings = issues.filter(i => i.severity === "warning").length;

    if (errors > 0) {
      updateStatus("error", `检查发现 ${errors} 个错误，${warnings} 个警告`);
    } else if (warnings > 0) {
      updateStatus("warning", `检查通过，存在 ${warnings} 个警告建议关注`);
    } else {
      updateStatus("ready", "检查完全通过！正文、公式、离线资源与锚点均完整。");
    }

    showDiagnosticsModal();
  } catch (e) {
    document.getElementById("btn-check-content").disabled = false;
    updateStatus("error", `检查出错: ${e}`);
  }
}

// Start Build HTML
async function handleStartBuild() {
  const req = getRequestParameters();
  if (!req.source_path_or_url) {
    alert("请先选择或输入内容来源");
    return;
  }
  if (currentMode === "folder" && (!req.source_data.include_files || req.source_data.include_files.length === 0)) {
    alert("请至少选择一个要合并的 Markdown 文件");
    return;
  }
  if (currentMode === "chatgpt" && (!req.source_data.messages || req.source_data.messages.length === 0)) {
    alert("请至少勾选一条要收录的消息");
    return;
  }
  if (!req.output) {
    alert("请指定保存位置 (保存到)");
    return;
  }

  // Switch UI to running state
  setActionState("running");
  updateStatus("running", "准备启动构建工作进程...", 0);

  try {
    const res = await api.start_build({
      source_type: req.source_type,
      source_data: req.source_data,
      output: req.output,
      config_path: req.config_path,
      overrides: req.overrides,
    });

    if (!res.success) {
      setActionState("idle");
      updateStatus("error", `启动构建失败: ${res.error}`);
      return;
    }

    currentJobId = res.job_id;
    startProgressPolling(currentJobId);
  } catch (e) {
    setActionState("idle");
    updateStatus("error", `启动任务出错: ${e}`);
  }
}

// Progress Polling
function startProgressPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = setInterval(async () => {
    try {
      const info = await api.get_job_status(jobId);
      if (!info.found) return;

      const p = info.progress || {};
      const stageName = p.message || p.stage || "进行中";
      const current = p.current || 0;
      const total = p.total || 1;
      const percent = total > 0 ? Math.round((current / total) * 100) : 0;

      updateStatus("running", stageName, percent);

      if (["success", "warning", "failed", "cancelled"].includes(info.status)) {
        clearInterval(pollTimer);
        pollTimer = null;
        handleJobFinished(info);
      }
    } catch (e) {
      console.error("Poll error:", e);
    }
  }, 350);
}

// Job Finished Handler
function handleJobFinished(jobInfo) {
  lastReport = jobInfo.result ? jobInfo.result.report : null;

  if (jobInfo.status === "success" || jobInfo.status === "warning") {
    setActionState("finished");
    const outPath = jobInfo.result ? jobInfo.result.output : "";
    updateStatus(jobInfo.status === "warning" ? "warning" : "ready", `生成成功！已导出为离线 HTML: ${outPath}`, 100);
  } else if (jobInfo.status === "cancelled") {
    setActionState("idle");
    updateStatus("ready", "构建已由用户取消，未生成或覆盖目标文件。", 0);
  } else {
    setActionState("idle");
    const errMsg = jobInfo.result ? jobInfo.result.error_message : "任务异常终止";
    updateStatus("error", `生成失败: ${errMsg}`, 0);
    showModal("生成失败", `<div class="diag-item error"><div class="diag-title">生成过程中发生错误</div><p>${escapeHtml(errMsg)}</p></div>`);
  }
}

// Cancel Build
async function handleCancelBuild() {
  if (!currentJobId) return;
  updateStatus("running", "正在取消任务并终止子进程...");
  await api.cancel_job(currentJobId);
}

// Action button state helper
function setActionState(state) {
  document.getElementById("actions-idle").style.display = state === "idle" ? "flex" : "none";
  document.getElementById("actions-running").style.display = state === "running" ? "flex" : "none";
  document.getElementById("actions-finished").style.display = state === "finished" ? "flex" : "none";

  const progressWrap = document.getElementById("progress-wrap");
  progressWrap.style.display = state === "running" ? "block" : "none";

  if (state === "idle") {
    const bar = document.getElementById("progress-bar");
    if (bar) bar.style.width = "0%";
    const checkBtn = document.getElementById("btn-check-content");
    const buildBtn = document.getElementById("btn-build");
    if (checkBtn) checkBtn.disabled = false;
    if (buildBtn) buildBtn.disabled = false;
  }
}

// Update status text & badge
function updateStatus(type, message, percent = null) {
  const badge = document.getElementById("status-badge");
  const msgEl = document.getElementById("status-message");
  const bar = document.getElementById("progress-bar");

  badge.className = "status-badge";
  if (type === "running" || type === "reading") {
    badge.classList.add("status-running");
    badge.textContent = type === "reading" ? "读取中" : "正在生成";
  } else if (type === "warning") {
    badge.classList.add("status-warning");
    badge.textContent = "有警告";
  } else if (type === "error") {
    badge.classList.add("status-error");
    badge.textContent = "错误";
  } else {
    badge.classList.add("status-ready");
    badge.textContent = "准备就绪";
  }

  msgEl.textContent = message;
  if (percent !== null) {
    bar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  }
}

// Modals
function showModal(title, bodyHtml) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-diag").style.display = "flex";
}

function closeModal() {
  document.getElementById("modal-diag").style.display = "none";
}

function showEnvModal(env) {
  let html = `
    <div style="margin-bottom:16px;">
      <p><strong>Python 版本:</strong> ${escapeHtml(env.python || "未知")}</p>
      <p><strong>Pandoc 路径:</strong> ${escapeHtml(env.pandoc_path || "未找到")} (${escapeHtml(env.pandoc_version || "未知")})</p>
      <p><strong>Node 路径:</strong> ${escapeHtml(env.node_path || "未找到")}</p>
      <p><strong>KaTeX / 字体:</strong> ${env.node_info ? escapeHtml(JSON.stringify(env.node_info)) : "不可用"}</p>
      <p><strong>HTML 模板:</strong> ${env.templates_intact ? "完整" : "缺失"}</p>
      <p><strong>GUI 后端:</strong> ${escapeHtml(env.gui_backend || "无")}</p>
    </div>
  `;

  if (env.risks && env.risks.length > 0) {
    html += `<h4 style="margin-bottom:8px; color:var(--danger-color)">发现的环境问题：</h4>`;
    env.risks.forEach(r => {
      html += `<div class="diag-item error">${escapeHtml(r)}</div>`;
    });
  } else {
    html += `<div class="diag-item info" style="border-left-color:var(--success-color); background:var(--success-bg)">
      <div class="diag-title" style="color:var(--success-color)">所有依赖正常</div>
      <p>本机具备完整的 Markdown 转换、Node 公式渲染及离线打包环境。</p>
    </div>`;
  }

  showModal("环境检查详情", html);
}

function showDiagnosticsModal() {
  if (!lastReport) {
    showModal("诊断报告", "<p>暂无最新诊断报告。请先点击“检查内容”或“生成 HTML”。</p>");
    return;
  }

  const issues = lastReport.issues || [];
  const stats = lastReport.stats || {};

  let html = `
    <div style="margin-bottom:16px; padding:10px; background:#f1f5f9; border-radius:6px;">
      <strong>统计概览：</strong>
      <span>收录文档 ${stats.documents || 0} 篇</span> ·
      <span>图片 ${stats.image_references || 0} 张</span> ·
      <span>数学公式 ${stats.math_expressions || 0} 处</span> ·
      <span>最终体积 ${formatBytes(stats.output_bytes || 0)}</span>
    </div>
  `;

  if (issues.length === 0) {
    html += `<div class="diag-item info" style="border-left-color:var(--success-color); background:var(--success-bg)">
      <div class="diag-title" style="color:var(--success-color)">无任何警告或错误</div>
      <p>内容格式完备，所有离线资源和锚点均通过完整性校验。</p>
    </div>`;
  } else {
    html += `<h4 style="margin-bottom:8px;">发现的问题与修复建议 (${issues.length})：</h4>`;
    issues.forEach(i => {
      const cls = i.severity === "error" ? "error" : (i.severity === "warning" ? "warning" : "info");
      html += `
        <div class="diag-item ${cls}">
          <div class="diag-title">[${escapeHtml(i.code)}] ${escapeHtml(i.message)}</div>
          <div style="font-size:12px; color:#64748b; margin-top:2px;">
            来源: ${escapeHtml(i.source || "(系统)")} ${i.line ? `· 行号: ${i.line}` : ""}
          </div>
          ${i.suggestion ? `<div style="font-size:12px; color:#0369a1; margin-top:4px;">💡 建议: ${escapeHtml(i.suggestion)}</div>` : ""}
        </div>
      `;
    });
  }

  showModal("诊断报告", html);
}

// Helpers
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}
