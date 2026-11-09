/* Desktop interactions; previews and game writes remain server-authoritative. */
(() => {
  'use strict';
  const {request,busy,notice,confirm} = window.Forever;
  const readState = key => { try { return JSON.parse(sessionStorage.getItem(key) || '{}'); } catch { return {}; } };
  const saveState = (key,value) => { try { sessionStorage.setItem(key,JSON.stringify(value)); } catch { /* Storage may be unavailable in private WebViews. */ } };
  const el = (tag,text,className) => { const node=document.createElement(tag);if(text != null) node.textContent=String(text);if(className) node.className=className;return node; };
  document.querySelectorAll('[data-map-x][data-map-y]').forEach(pin=>{
    const x=Number(pin.dataset.mapX),y=Number(pin.dataset.mapY);
    if(Number.isFinite(x)&&Number.isFinite(y)&&x>=0&&x<=100&&y>=0&&y<=100){pin.style.left=`${x}%`;pin.style.top=`${y}%`;}
    else pin.hidden=true;
  });
  document.addEventListener('error', event => {
    if (event.target instanceof HTMLImageElement) { event.target.classList.add('image-unavailable');event.target.alt = event.target.alt || '图片暂不可用'; }
  },true);
  const imageDialog=document.querySelector('#image-dialog');
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-image]');
    if(button){imageDialog.querySelector('img').src=button.dataset.image;imageDialog.querySelector('img').alt=button.dataset.caption || '';imageDialog.querySelector('p').textContent=button.dataset.caption || '';imageDialog.showModal();}
    if(event.target.closest('[data-close-image]')) imageDialog.close();
  });
  const importDialog=document.querySelector('#import-dialog');
  document.querySelector('[data-open-import]')?.addEventListener('click',()=>importDialog.showModal());
  document.querySelector('[data-close-import]')?.addEventListener('click',()=>importDialog.close());
  if(importDialog){
    if(new URLSearchParams(location.search).get('import')==='zip')importDialog.showModal();
    const drop=document.querySelector('#zip-drop'),file=document.querySelector('#addon_zip');
    document.addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files')){event.preventDefault();drop.classList.add('drag-over');}});
    document.addEventListener('dragleave',()=>drop.classList.remove('drag-over'));
    document.addEventListener('drop',event=>{if(!event.dataTransfer.files.length)return;event.preventDefault();drop.classList.remove('drag-over');
      const files=event.dataTransfer.files;
      if(files.length!==1 || !files[0].name.toLowerCase().endsWith('.zip')){notice('请一次拖入一个 ZIP 发布包。',true);return;}
      if(files[0].size>128*1048576){notice('ZIP 超过 128 MiB，请选择较小的发布包。',true);return;}
      file.files=files;if(!importDialog.open)importDialog.showModal();
    });
  }
  const manager=document.querySelector('#addon-manager');
  if(manager){
    const table=manager.querySelector('.addon-table'), rows=[...manager.querySelectorAll('[data-addon-id]')];
    const search=document.querySelector('#addon-search'),status=document.querySelector('#addon-status'),sort=document.querySelector('#addon-sort'),character=document.querySelector('#addon-character'),all=document.querySelector('#select-all-addons');
    const key='forever-addons:'+document.querySelector('#global-character')?.value;
    const state=readState(key), selected=new Set(state.selected||[]);let last=null;
    search.value=state.q||'';status.value=state.status||'all';sort.value=state.sort||'name';
    if(state.character && [...character.options].some(o=>o.value===state.character))character.value=state.character;
    const persist=()=>saveState(key,{q:search.value,status:status.value,sort:sort.value,character:character.value,selected:[...selected],scroll:window.scrollY});
    const visible=()=>rows.filter(row=>!row.hidden);
    const updateSelection=()=>{
      rows.forEach(row=>{const checked=selected.has(row.dataset.addonId);row.querySelector('.addon-check').checked=checked;row.classList.toggle('selected',checked);});
      const count=rows.filter(row=>selected.has(row.dataset.addonId)).length;
      document.querySelector('#selection-count').textContent=count ? `已选择 ${count} 个` : '未选择插件';
      document.querySelectorAll('[data-manage]').forEach(button=>button.disabled=!count || (['enable','disable'].includes(button.dataset.manage)&&!character.value));
      const vis=visible(),checked=vis.filter(row=>selected.has(row.dataset.addonId)).length;all.checked=!!vis.length&&checked===vis.length;all.indeterminate=checked>0&&checked<vis.length;persist();
    };
    const filter=()=>{
      const q=search.value.trim().toLocaleLowerCase();
      const ordered=[...rows].sort((a,b)=>sort.value==='update'?(Number(b.dataset.update==='release_differs')-Number(a.dataset.update==='release_differs') || a.dataset.name.localeCompare(b.dataset.name)):sort.value==='category'?(a.dataset.category.localeCompare(b.dataset.category)||a.dataset.name.localeCompare(b.dataset.name)):a.dataset.name.localeCompare(b.dataset.name));
      ordered.forEach(row=>{const value=status.value;row.hidden=!row.dataset.search.toLocaleLowerCase().includes(q) || !(value==='all'||row.dataset.update===value||row.dataset.enablement===value);table.append(row);});
      rows.splice(0,rows.length,...ordered);document.querySelector('#visible-count').textContent=`${visible().length} / ${rows.length} 个插件`;document.querySelector('#addon-no-results').hidden=visible().length!==0;updateSelection();
    };
    [search,status,sort].forEach(control=>control.addEventListener(control===search?'input':'change',filter));
    rows.forEach(row=>row.querySelector('.addon-check').addEventListener('click',event=>{
      const checkbox=event.currentTarget,list=visible(),index=list.indexOf(row);
      if(event.shiftKey && last && list.includes(last)){const other=list.indexOf(last);list.slice(Math.min(index,other),Math.max(index,other)+1).forEach(r=>checkbox.checked?selected.add(r.dataset.addonId):selected.delete(r.dataset.addonId));}
      else checkbox.checked?selected.add(row.dataset.addonId):selected.delete(row.dataset.addonId);
      last=row;updateSelection();
    }));
    all.addEventListener('change',()=>{visible().forEach(row=>all.checked?selected.add(row.dataset.addonId):selected.delete(row.dataset.addonId));updateSelection();});
    document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='a'&&!event.target.closest('input:not([type=checkbox]),textarea,select,dialog')){event.preventDefault();visible().forEach(row=>selected.add(row.dataset.addonId));updateSelection();}});
    let enablementSequence=0;
    const loadEnablement=async()=>{
      const sequence=++enablementSequence;
      try{const data=await request('/api/addons/enablement'+(character.value?'?character_id='+encodeURIComponent(character.value):''),undefined,'GET');if(sequence!==enablementSequence)return;
        const map=new Map(data.packages.map(p=>[p.id,p]));rows.forEach(row=>{const p=map.get(row.dataset.addonId);row.dataset.enablement=p?.status||'unknown';const tag=row.querySelector('[data-enablement]');tag.textContent=character.value?({enabled:'已启用',disabled:'已停用',mixed:'部分启用',unknown:'状态未知'})[p?.status||'unknown']:'选择角色';tag.classList.toggle('tag-live',p?.status==='enabled');});filter();
      }catch(error){notice(error.message,true);}
    };
    character.addEventListener('change',()=>{persist();loadEnablement();});
    document.querySelectorAll('[data-manage]').forEach(button=>button.addEventListener('click',()=>busy(button,async()=>{
      persist();const action=button.dataset.manage;
      const plan=await request('/api/addons/management/plans',{action,package_ids:rows.filter(row=>selected.has(row.dataset.addonId)).map(row=>row.dataset.addonId),...(['enable','disable'].includes(action)?{character_id:character.value}:{})});
      location.assign('/addons/management/'+encodeURIComponent(plan.id));
    })));
    filter();loadEnablement();requestAnimationFrame(()=>window.scrollTo(0,state.scroll||0));window.addEventListener('pagehide',persist);
  }
  document.querySelector('[data-management-apply]')?.addEventListener('click',event=>{const button=event.currentTarget;busy(button,async()=>{
    if(!await confirm('按本页预览应用这些变更？将自动备份，失败时停止剩余项目。'))return;
    await request('/api/addons/management/plans/'+button.dataset.managementApply+'/apply');location.reload();
  });});
  const bag=document.querySelector('#bag-browser');
  if(bag){
    const controls=['bag-search','bag-category','bag-quality','bag-location','bag-sort'].map(id=>document.getElementById(id));
    const [search,category,quality,location,sort]=controls,grid=document.querySelector('#bag-grid'),rows=[...grid.querySelectorAll('[data-item]')];
    const key='forever-bags:'+bag.dataset.character, saved=readState(key);controls.forEach(c=>{if(saved[c.id]!=null)c.value=saved[c.id];});
    const persist=()=>saveState(key,{...Object.fromEntries(controls.map(c=>[c.id,c.value])),scroll:window.scrollY});
    const data=new Map(rows.map(row=>[row,JSON.parse(row.dataset.item)]));
    const filter=()=>{
      const query=search.value.trim().toLocaleLowerCase();
      rows.sort((a,b)=>{const x=data.get(a),y=data.get(b);if(sort.value==='name')return (x.name||'').localeCompare(y.name||'');if(sort.value==='quality')return (y.quality??-1)-(x.quality??-1);if(sort.value==='count')return y.count-x.count;return (x.bag??99)-(y.bag??99)||(x.bag_slot??999)-(y.bag_slot??999);});
      rows.forEach(row=>{const d=data.get(row);row.hidden=!`${d.name||''} ${d.item_id||''}`.toLocaleLowerCase().includes(query)||(category.value&&category.value!==d.category)||(quality.value&&Number(quality.value)!==d.quality)||(location.value&&Number(location.value)!==d.bag);grid.append(row);});
      const count=rows.filter(row=>!row.hidden).length;document.querySelector('#bag-count').textContent=`${count} / ${rows.length} 项物品`;document.querySelector('#bag-no-results').hidden=count>0;persist();
    };
    controls.forEach(c=>c.addEventListener(c===search?'input':'change',filter));
    const dialog=document.querySelector('#bag-item-dialog'),form=document.querySelector('#bag-compare-form');let chosen=null;
    document.querySelector('[data-close-bag]')?.addEventListener('click',()=>dialog.close());
    rows.forEach(row=>row.addEventListener('click',()=>{
      chosen=data.get(row);const d=chosen;document.querySelector('#bag-item-name').textContent=d.name||'名称未读取';document.querySelector('#bag-item-quality').textContent=d.quality_name+' · '+d.category;
      const picture=document.querySelector('#bag-item-picture');picture.replaceChildren();if(d.icon_url){const img=el('img');img.src=d.icon_url;img.alt=d.name||'物品';picture.append(img);}else picture.textContent='无图标';
      document.querySelector('#bag-item-position').textContent=`数量 ${d.count} · 行囊 ${d.bag??'未知'} / 位置 ${d.bag_slot??'未知'} · 物品等级 ${d.item_level??'未读取'}`;
      const stats=document.querySelector('#bag-item-stats');stats.replaceChildren(...d.stats_display.map(stat=>{const node=el('div',null,'stat-value');node.append(el('span',stat.label),el('b',stat.display??stat.value??'未知'));return node;}));
      if(!d.stats_display.length)stats.append(el('p','快照未包含可展示的属性。','muted'));
      const link=document.querySelector('#bag-reference');link.hidden=!d.reference_url;if(d.reference_url)link.href=d.reference_url;
      const slots=document.querySelector('#bag-compare-slot');slots.replaceChildren(...d.compare_slots.map(slot=>{const option=el('option',slot.name);option.value=slot.id;return option;}));
      form.hidden=!d.compare_slots.length;document.querySelector('#bag-compare-result').replaceChildren();dialog.showModal();
    }));
    form.addEventListener('submit',event=>{event.preventDefault();const selected=chosen;busy(form.querySelector('button'),async()=>{
      const result=await request('/api/equipment/compare',{slot:Number(document.querySelector('#bag-compare-slot').value),candidate_kind:'bag',bag_index:selected.index,expected_snapshot_id:bag.dataset.snapshot});
      const host=document.querySelector('#bag-compare-result');host.replaceChildren(el('h3',result.current.name+' → '+result.candidate.name));
      const table=el('table'),head=el('tr');['属性','当前','候选','变化'].forEach(t=>head.append(el('th',t)));table.append(head);
      result.deltas.forEach(d=>{const row=el('tr');[d.label,d.current??'未知',d.candidate??'未知',d.delta==null?'未知':(d.delta>0?'+':'')+d.delta].forEach(v=>row.append(el('td',v)));table.append(row);});
      const scroll=el('div',null,'table-scroll');scroll.append(table);host.append(scroll,el('p',result.conclusion,'field-hint'));
      result.unknowns.forEach(text=>host.append(el('p',text,'field-hint')));
    });});
    filter();requestAnimationFrame(()=>window.scrollTo(0,saved.scroll||0));window.addEventListener('pagehide',persist);
  }
  const profileCharacter=document.querySelector('#profile-character');
  if(profileCharacter){
    let sequence=0;
    const refresh=async()=>{
      const seq=++sequence;
      document.querySelector('#profile-preview').hidden=true;
      if(!profileCharacter.value){document.querySelectorAll('[data-profile-status]').forEach(t=>t.textContent='选择角色');return;}
      try{const data=await request('/api/addons/enablement?character_id='+encodeURIComponent(profileCharacter.value),undefined,'GET');if(seq!==sequence)return;
        const groups=new Map(data.packages.map(p=>[p.id,p]));
        document.querySelectorAll('[data-profile-status]').forEach(tag=>{const group=groups.get(tag.dataset.profileStatus==='ForeverUI'?'local-ForeverUI':'ellesmere');tag.textContent=group?({enabled:'已启用',disabled:'已停用',mixed:'部分启用',unknown:'状态未知'})[group.status]:'尚未安装';tag.classList.toggle('tag-live',group?.status==='enabled');});
        document.querySelector('#profile-current').textContent='当前读取：'+(data.character.display_name||data.character.character)+' · 启用状态';
      }catch(error){notice(error.message,true);}
    };
    profileCharacter.addEventListener('change',refresh);refresh();
  }
  document.querySelector('#market-selection-form')?.addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;busy(form.querySelector('button'),async()=>{const house=form.querySelector('select').value;await request('/api/market/selection',{house:house||null});if(house)await request('/api/market/refresh');notice(house?'参考市场已保存并同步。':'已关闭公开参考市场。');});});
  document.querySelector('[data-market-discover]')?.addEventListener('click',event=>busy(event.currentTarget,async()=>{
    const report=await request('/api/market/markets?refresh=true',undefined,'GET'),select=document.querySelector('#market-house');select.replaceChildren(el('option','不使用公开参考市场'));select.firstChild.value='';
    report.markets.forEach(m=>{const option=el('option',m.label||m.key);option.value=m.key;option.selected=option.value===report.selected_house;select.append(option);});notice('已刷新可用市场。');
  }));
})();
