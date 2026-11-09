/* Local platform interactions. Sources and installation decisions stay on the server. */
(() => {
  'use strict';
  const notice = (message, error = false) => {
    const host = document.querySelector('#global-notice');
    const node = document.createElement('div');
    node.className = 'notice' + (error ? ' notice-error' : '');
    node.setAttribute('role', error ? 'alert' : 'status');
    node.textContent = message;
    host.replaceChildren(node);
    if (error) host.scrollIntoView({block: 'nearest'});
  };
  const request = async (url, data = {}, method = 'POST', upload = false) => {
    const response = await fetch(url, {method, headers: upload ? {} : {'Content-Type': 'application/json'}, body: method === 'GET' ? undefined : upload ? data : JSON.stringify(data)});
    let result;
    try { result = await response.json(); } catch { throw new Error('本地服务没有返回完整结果，请查看操作历史后重试。'); }
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '输入格式无效，请检查后重试。');
    return result;
  };
  const confirm = message => new Promise(resolve => {
    const dialog = document.querySelector('#confirm-dialog');
    if (dialog.open) { resolve(false); return; }
    dialog.querySelector('#confirm-message').textContent = message;
    dialog.returnValue = '';
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once:true});
    dialog.showModal();
  });
  const previewRestore = async (id, characterId = null) => {
    const base = characterId ? '/api/profiles/snapshots/' + encodeURIComponent(id) : '/api/addons/operations/' + encodeURIComponent(id);
    const plan = await request(base + (characterId ? '/restore-preview?character_id=' + encodeURIComponent(characterId) : '/rollback-preview'), undefined, 'GET');
    let dialog = document.querySelector('#restore-dialog');
    if (!dialog) { dialog=document.createElement('dialog');dialog.id='restore-dialog';dialog.setAttribute('aria-label','恢复变更预览');document.body.append(dialog); }
    dialog.replaceChildren();
    const heading=document.createElement('h2');heading.textContent='恢复变更预览';dialog.append(heading);
    if(plan.character){const who=document.createElement('p');who.textContent=(plan.character.display_name||plan.character.character)+' · '+plan.combo;dialog.append(who);}
    const rows=plan.files||plan.before_after||[];
    rows.forEach(change=>{
      const row=document.createElement('div');row.className='history-row';
      const name=document.createElement('b');name.textContent=change.filename||change.target.split('/').pop();
      const state=document.createElement('span');state.className='tag';state.textContent=({remove:'移除',restore:'恢复',replace:'替换',unchanged:'内容一致'})[change.action]||'恢复';
      row.append(name,state);
      const note=document.createElement('small');
      note.textContent=change.scope ? (change.scope==='account'?'账号共享配置：会影响同账号角色':'选定角色配置') : (change.before?.kind==='directory'||change.after?.kind==='directory') ? '当前 '+change.files_before+' 个文件 → 备份 '+change.files_after+' 个文件' : '恢复角色插件启用状态';
      row.append(note);
      const details=document.createElement('details'),summary=document.createElement('summary'),target=document.createElement('p');summary.textContent='查看路径';target.className='mono-wrap';target.textContent=change.target;details.append(summary,target);row.append(details);dialog.append(row);
    });
    const backup=document.createElement('p');backup.className='field-hint';backup.textContent=plan.backup;dialog.append(backup);
    (plan.blockers||[]).forEach(message=>{const error=document.createElement('p');error.className='notice notice-error';error.textContent=message;dialog.append(error);});
    const actions=document.createElement('div');actions.className='form-actions';
    const cancel=document.createElement('button');cancel.className='button button-quiet';cancel.textContent='取消';cancel.onclick=()=>dialog.close();
    const apply=document.createElement('button');apply.className='button button-primary';apply.textContent='确认恢复';apply.disabled=!plan.can_apply;
    apply.onclick=()=>busy(apply,async()=>{
      await request(base+(characterId?'/restore':'/rollback'),{precondition_token:plan.precondition_token,...(characterId?{character_id:characterId}:{})});
      location.assign('/downloads');
    });
    actions.append(cancel,apply);dialog.append(actions);dialog.showModal();
  };
  const busy = async (control, action) => {
    const text = control.textContent;
    control.disabled = true;
    control.setAttribute('aria-busy', 'true');
    control.textContent = '处理中…';
    notice('正在处理，任务完成后会显示结果。');
    const region = control.closest('dialog, form, .panel');
    region?.querySelectorAll('.action-notice').forEach(item => item.remove());
    try { await action(); } catch (error) {
      notice(error.message, true);
      if (region) { const inline = document.createElement('p'); inline.className='notice notice-error action-notice'; inline.setAttribute('role','alert'); inline.textContent=error.message + ' · 可修正后重试。'; region.append(inline); }
    }
    finally { control.disabled = control.dataset.keepDisabled === 'true'; control.removeAttribute('aria-busy'); control.textContent = control.dataset.finalText || text; }
  };
  const routeResult = (host, result) => {
    if (host.hasAttribute('data-profile-preview')) { location.assign('/profiles/plans/' + encodeURIComponent(result.id)); return; }
    if (host.hasAttribute('data-plan')) { location.assign('/addons/plans/' + encodeURIComponent(result.id)); return; }
    if (host.hasAttribute('data-project')) { location.assign('/workshop?project=' + encodeURIComponent(result.id)); return; }
    if (host.hasAttribute('data-home')) { location.assign('/downloads'); return; }
    if (host.hasAttribute('data-reload')) { location.reload(); return; }
    if (host.hasAttribute('data-launch-game')) { host.dataset.keepDisabled = String(result.status === 'already_running' || result.status === 'starting'); host.dataset.finalText = result.status === 'already_running' ? '游戏运行中' : result.status === 'starting' ? '游戏启动中' : '通过战网启动'; }
    notice(result.note || '操作完成。');
  };
  window.Forever = {request, busy, notice, confirm, previewRestore};
  document.addEventListener('click', async event => {
    const button = event.target.closest('button[data-api]');
    if (!button || button.disabled) return;
    if (button.dataset.restoreOperation) { busy(button,()=>previewRestore(button.dataset.restoreOperation)); return; }
    if (button.dataset.confirm && !await confirm(button.dataset.confirm)) return;
    busy(button, async () => routeResult(button, await request(button.dataset.api, JSON.parse(button.dataset.json || '{}'))));
  });
  document.querySelectorAll('[data-platform-form]').forEach(form => form.addEventListener('submit', event => {
    event.preventDefault();
    const submit = form.querySelector('button[type=submit]');
    const data = new FormData(form);
    busy(submit, async () => routeResult(form, await request(form.dataset.api, form.hasAttribute('data-upload') ? data : Object.fromEntries(data), 'POST', form.hasAttribute('data-upload'))));
  }));
  const character = () => {
    const id = document.querySelector('#profile-character')?.value;
    if (!id) throw new Error('请先选择已保存插件设置的角色。');
    return id;
  };
  document.querySelectorAll('[data-profile-plan]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
    const plan = await request('/api/profiles/plans', {character_id: character(), combo: button.dataset.profilePlan, keep_ellesmere_dps: Boolean(document.querySelector('#profile-keep-eui-dps')?.checked)});
    const host = document.querySelector('#profile-preview');
    host.hidden = false;
    document.querySelector('#profile-preview-note').textContent = plan.note;
    const changes = document.querySelector('#profile-preview-changes');
    changes.replaceChildren(...Object.entries(plan.updates).map(([name, enabled]) => {
      const row = document.createElement('p'); row.textContent = `${enabled ? '启用' : '停用'} · ${name}`; return row;
    }));
    const apply = document.querySelector('#profile-apply');
    apply.onclick = () => busy(apply, async () => {
      if (character() !== plan.character_id) throw new Error('所选角色已变化，请重新预览切换。');
      if (!await confirm('按预览调整所选角色的插件启用状态？将先备份当前设置。')) return;
      await request('/api/profiles/plans/' + plan.id + '/apply');
      location.assign('/downloads');
    });
    host.scrollIntoView({block: 'nearest'});
    notice('切换预览已生成，确认后点击应用。');
  })));
  document.querySelectorAll('[data-profile-backup]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
    await request('/api/profiles/snapshots', {character_id: character(), combo: button.dataset.profileBackup});
    location.reload();
  })));
  document.querySelectorAll('[data-profile-restore]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
    if (character() !== button.dataset.character) throw new Error('请选择这份备份对应的角色。');
    await previewRestore(button.dataset.profileRestore, character());
  })));
  const editor = document.querySelector('[data-project-id]');
  if (editor) {
    const project = editor.dataset.projectId;
    const prefix = '/api/workshop/projects/' + project;
    const pathInput = document.querySelector('#source-path');
    const source = document.querySelector('#source-content');
    const result = document.querySelector('#workshop-result');
    let readPath = null, readHash = null, dirty = false;
    source.addEventListener('input', () => { dirty = true; });
    const show = value => {
      const output = document.createElement('pre'); output.className = 'platform-output';
      output.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
      result.replaceChildren(output);
    };
    document.querySelectorAll('[data-open-file]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
      if (dirty && !await confirm('离开当前文件并放弃未保存编辑？')) return;
      const file = await request(prefix + '/file?path=' + encodeURIComponent(button.dataset.openFile), undefined, 'GET');
      pathInput.value = file.path; source.value = file.content; readPath = file.path; readHash = file.sha256; dirty = false;
      document.querySelectorAll('[data-open-file]').forEach(item => item.classList.toggle('selected', item === button));
      notice('已读取工作区文件。');
    })));
    document.querySelector('#save-source').addEventListener('click', event => busy(event.currentTarget, async () => {
      const saved = await request(prefix + '/file', {path: pathInput.value, content: source.value, expected_sha256: pathInput.value === readPath ? readHash : null}, 'PUT');
      readPath = pathInput.value; readHash = saved.after; dirty = false;
      show('已保存工作区文件。刷新可查看更新后的文件列表与修改历史。');
      notice('已保存。游戏目录保持原样。');
    }));
    document.querySelectorAll('[data-workshop-action]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
      if (dirty) throw new Error('请先保存源码，再检查或打包。');
      const action = button.dataset.workshopAction;
      const report = await request(prefix + '/' + action, undefined, action === 'diff' ? 'GET' : 'POST');
      if (action === 'pack') {
        show('打包完成。可以下载 ZIP，或生成安装计划查看变更。');
        const actions = document.createElement('div'); actions.className = 'platform-actions';
        const link = document.createElement('a'); link.className = 'button button-secondary'; link.href = report.url; link.textContent = '下载 ZIP'; link.download = '';
        const plan = document.createElement('button'); plan.className = 'button button-primary'; plan.textContent = '生成安装计划';
        plan.onclick = () => busy(plan, async () => { const item = await request(report.url + '/plan'); location.assign('/addons/plans/' + item.id); });
        actions.append(link, plan); result.append(actions);
      } else show(action === 'diff' ? (report.diff || '与基线一致。') : report);
      notice(action === 'validate' ? report.passed ? '检查通过。游戏内表现仍需验证。' : '检查发现问题，请查看结果。' : '操作完成。', action === 'validate' && !report.passed);
    })));
    window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  }
  document.querySelector('#api-lookup-form')?.addEventListener('submit', event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    busy(button, async () => {
      const report = await request('/api/workshop/api?q=' + encodeURIComponent(document.querySelector('#api-query').value), undefined, 'GET');
      const output = document.querySelector('#api-lookup-result'); output.hidden = false; output.textContent = JSON.stringify(report, null, 2);
      notice('已查询本地版本资料。');
    });
  });
  const launchButton = document.querySelector('[data-launch-game]');
  if (launchButton) {
    const syncLaunch = async () => {
      try {
        const state = await request('/api/addons/game-status', undefined, 'GET');
        if (launchButton.getAttribute('aria-busy') === 'true') return;
        const disabled = !state.available || state.running || state.starting;
        launchButton.disabled = disabled; launchButton.dataset.keepDisabled = String(disabled);
        launchButton.textContent = state.running ? '游戏运行中' : state.starting ? '游戏启动中' : '通过战网启动';
        launchButton.dataset.finalText = launchButton.textContent; launchButton.title = state.note;
      } catch { /* Main page handles connection errors. */ }
    };
    window.setInterval(syncLaunch, 4000);
  }
  const taskHost = document.querySelector('#platform-tasks');
  {
    const loadTasks = async () => {
      try {
        const tasks = await request('/api/addons/tasks', undefined, 'GET');
        const active = tasks.filter(task => task.status === 'running').length;
        const badge = document.querySelector('#task-count');
        if (badge) { badge.hidden = !active; badge.textContent = String(active); }
        if (!taskHost) return;
        taskHost.replaceChildren(...tasks.slice(0, 20).map(task => {
          const row = document.createElement('div'); row.className = 'history-row';
          const label = document.createElement('b'); label.textContent = task.label;
          const state = document.createElement('span'); state.className = 'tag';
          state.textContent = ({running:'处理中', completed:'已完成', failed:'未完成', interrupted:'已中断'})[task.status];
          row.append(label, state);
          if (task.stage) {
            const progress = document.createElement('div'); progress.className='task-progress';
            const stages = {checking_release:'核对作者发布',downloading:'下载文件',validating:'校验文件',awaiting_confirmation:'等待确认',backing_up:'备份原文件',applying:'应用文件',completed:'完成',failed:'未完成'};
            progress.textContent = stages[task.stage] || task.stage;
            if (task.bytes_received != null) progress.textContent += ' · ' + (task.bytes_received/1048576).toFixed(1) + ' MiB' + (task.bytes_total ? ' / ' + (task.bytes_total/1048576).toFixed(1) + ' MiB' : '');
            if (task.bytes_total && task.status === 'running') { const bar=document.createElement('progress');bar.max=task.bytes_total;bar.value=task.bytes_received || 0;progress.append(bar); }
            row.append(progress);
          }
          if (task.message) { const note = document.createElement('span'); note.textContent = task.message; row.append(note); }
          if (task.plan_id) { const link = document.createElement('a'); link.className = 'text-link'; link.href = (task.plan_kind === 'management' ? '/addons/management/' : '/addons/plans/') + encodeURIComponent(task.plan_id); link.textContent = '查看计划 →'; row.append(link); }
          return row;
        }));
        if (!tasks.length) taskHost.textContent = '暂无下载或准备任务。';
      } catch { /* Current mutation or main page reports connection failures. */ }
    };
    loadTasks();
    window.setInterval(loadTasks, 4000);
  }
})();
