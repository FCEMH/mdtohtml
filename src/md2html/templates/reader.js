'use strict';
(() => {
  const $ = selector => document.querySelector(selector);
  const data = JSON.parse($('#md2html-index').textContent);
  const root = document.documentElement;
  const systemDark = () => typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
  try { const saved = localStorage.getItem('md2html-theme'); if (['auto','light','dark'].includes(saved)) root.dataset.theme = saved; } catch (_) {}
  $('#theme-toggle').addEventListener('click', () => {
    const dark = root.dataset.theme === 'dark' || root.dataset.theme === 'auto' && systemDark();
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('md2html-theme', root.dataset.theme); } catch (_) {}
    $('#theme-toggle').setAttribute('aria-label', `切换到${dark ? '深色' : '浅色'}主题`);
  });
  const sidebar = $('#sidebar'), menu = $('#menu'), backdrop = $('#sidebar-backdrop');
  const closeSidebar = () => {sidebar.classList.remove('open'); backdrop.hidden = true; menu.setAttribute('aria-expanded','false');};
  menu.addEventListener('click', () => {const open = sidebar.classList.toggle('open'); backdrop.hidden = !open; menu.setAttribute('aria-expanded', String(open));});
  backdrop.addEventListener('click', closeSidebar);
  sidebar.addEventListener('click', event => {if (event.target.closest('a')) closeSidebar();});
  const allNav = Array.from(sidebar.querySelectorAll('a'));
  const chapters = Array.from(document.querySelectorAll('.chapter'));
  let activeId = '';
  function activate(id) {
    if (id === activeId) return;
    activeId = id;
    const chapterElement = document.getElementById(id)?.closest('.chapter');
    const navId = allNav.some(a => decodeURIComponent(a.hash) === '#' + id) ? id : chapterElement?.id;
    allNav.forEach(a => {const current = a.hash === '#' + navId || decodeURIComponent(a.hash) === '#' + navId; a.classList.toggle('active',current); if (current) {a.setAttribute('aria-current','location'); let parent=a.parentElement; while (parent && parent !== sidebar) {if(parent.tagName === 'DETAILS') parent.open = true; parent=parent.parentElement;}} else a.removeAttribute('aria-current');});
    const chapter = document.getElementById(id)?.closest('.chapter');
    if (chapter) $('#current-chapter').textContent = chapter.getAttribute('aria-label');
  }
  const targets = Array.from(document.querySelectorAll('.chapter, .chapter h2[id], .chapter h3[id], .chapter h4[id], .chapter h5[id], .chapter h6[id]'));
  let pending = false;
  function updatePosition() {
    pending = false;
    let last = null;
    for (const item of targets) {if (item.getBoundingClientRect().top <= 150) last = item; else break;}
    if (last) activate(last.id); else {activeId=''; allNav.forEach(a=>{a.classList.remove('active');a.removeAttribute('aria-current');}); $('#current-chapter').textContent='阅读起点';}
    const total = Math.max(1, root.scrollHeight - innerHeight);
    const percent = Math.min(100, Math.max(0, Math.round(scrollY/total*100)));
    $('#progress').style.width = percent + '%'; $('#progress-label').textContent = percent + '%';
  }
  addEventListener('scroll', () => {if (!pending) {pending=true; requestAnimationFrame(updatePosition);}}, {passive:true});
  if ('IntersectionObserver' in window) new IntersectionObserver(updatePosition,{rootMargin:'-80px 0px -60% 0px'}).observe($('#main'));
  addEventListener('resize',updatePosition);
  function revealHash() {
    try {const id = decodeURIComponent(location.hash.slice(1)); const el = document.getElementById(id); if (!el) return; el.querySelector('.attachment-content')?.setAttribute('open',''); activate(id); let parent = el.parentElement; while (parent) {if (parent.tagName === 'DETAILS') parent.open = true; parent=parent.parentElement;}} catch (_) {}
  }
  addEventListener('hashchange',revealHash); revealHash(); updatePosition();
  const toast = message => {$('#toast').textContent=message; $('#toast').classList.add('visible'); setTimeout(()=>$('#toast').classList.remove('visible'),2000);};
  for (const pre of document.querySelectorAll('.chapter pre')) {
    const code = pre.querySelector('code'); if (!code) continue;
    const original = code.textContent;
    const block = pre.parentElement.classList.contains('sourceCode') ? pre.parentElement : pre;
    const shell = document.createElement('div'); shell.className='code-shell'; block.before(shell); shell.append(block);
    const bar=document.createElement('div'); bar.className='code-toolbar';
    const label=document.createElement('span'); label.textContent=Array.from(code.classList).find(c=>!['sourceCode','numberSource'].includes(c)) || 'code';
    const button=document.createElement('button'); button.className='copy-code'; button.textContent='复制代码'; button.type='button'; bar.append(label,button); shell.prepend(bar);
    button.addEventListener('click',async()=>{try {let copied=false; try {if(navigator.clipboard?.writeText) {await navigator.clipboard.writeText(original); copied=true;}} catch (_) {}
      if (!copied) {const input=document.createElement('textarea'); input.value=original; input.className='copy-textarea'; input.setAttribute('aria-label','待复制代码'); document.body.append(input); input.select(); copied=document.execCommand('copy'); input.remove(); button.focus();}
      if (!copied) throw Error('clipboard unavailable'); button.textContent='已复制'; toast('代码已复制'); setTimeout(()=>button.textContent='复制代码',1800);
    } catch (_) {button.textContent='复制不可用'; toast('浏览器禁止复制，请直接选择代码文本。');}});
  }
  for (const table of document.querySelectorAll('.chapter table')) {const box=document.createElement('div'); box.className='table-scroll'; box.tabIndex=0; box.setAttribute('role','region'); box.setAttribute('aria-label','可横向滚动的表格'); table.before(box); box.append(table);}
  const imageDialog=$('#image-dialog');
  if (data.lightbox) for (const img of document.querySelectorAll('.chapter img, .attachment img')) {
    img.tabIndex=0; img.setAttribute('role','button'); img.setAttribute('aria-label', '放大图片：'+img.alt);
    const open=()=>{$('#lightbox-image').src=img.src; $('#lightbox-image').alt=img.alt; $('#lightbox-caption').textContent=img.alt; imageDialog.showModal();};
    img.addEventListener('click',event=>{event.preventDefault();open();}); img.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ') {e.preventDefault();open();}});
    if(img.height) img.style.setProperty('--image-height',img.getAttribute('height')+'px');
  }
  $('#image-close').addEventListener('click',()=>imageDialog.close());
  const dialog=$('#search-dialog');
  if (dialog) {
    const input=$('#search-input'), status=$('#search-status'), results=$('#search-results');
    const fold=s=>Array.from(s.normalize('NFKC')).map(ch=>data.casefold[ch] || ch.toLowerCase()).join('');
    const entries=data.entries.map(entry=>({...entry,folded:fold(entry.text)}));
    const open=()=>{if(!dialog.open) dialog.showModal(); input.focus(); input.select();};
    $('#search-open').addEventListener('click',open); $('#search-close').addEventListener('click',()=>dialog.close());
    function search() {
      const query=fold(input.value.trim()); results.replaceChildren();
      if (!query) {status.textContent='输入中文或英文关键词，直接搜索全文。';return;}
      const matches=entries.filter(entry=>entry.folded.includes(query));
      status.textContent=matches.length ? `找到 ${matches.length} 处匹配${matches.length>100?'，显示前 100 条':''}` : '没有找到结果，试试其他关键词。';
      for(const entry of matches.slice(0,100)) {
        const li=document.createElement('li'), a=document.createElement('a'), title=document.createElement('strong'), snippet=document.createElement('span'), source=document.createElement('small');
        a.href='#'+entry.id; title.textContent=entry.chapter; source.textContent=entry.source;
        const direct=entry.text.toLowerCase().indexOf(input.value.trim().toLowerCase());
        const position=Math.max(0,direct<0?0:direct-32), excerpt=entry.text.slice(position,position+140);
        if(direct>=0) {const offset=direct-position, mark=document.createElement('mark'); mark.textContent=excerpt.slice(offset,offset+input.value.trim().length);snippet.append(document.createTextNode((position?'…':'')+excerpt.slice(0,offset)),mark,document.createTextNode(excerpt.slice(offset+input.value.trim().length)));} else snippet.textContent=excerpt;
        a.append(title,snippet,source);li.append(a);results.append(li);
        a.addEventListener('click',()=>{dialog.close();closeSidebar();});
      }
    }
    input.addEventListener('input',search);
    input.addEventListener('keydown',e=>{if(e.key==='Enter'){const first=results.querySelector('a');if(first){e.preventDefault();first.click();}}});
    document.addEventListener('keydown',e=>{const editing=e.target.closest('input,textarea,select,[contenteditable="true"]'); if(e.key==='Escape'){if(dialog.open)dialog.close();closeSidebar();return;} if(!editing && ((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'||e.key==='/')) {e.preventDefault();open();}});
  }
  for(const modal of document.querySelectorAll('dialog')) modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)modal.close();}});
})();
