import asyncio
import json
from pathlib import Path
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from backend.ai import Advisor
from backend.codex_bridge import CodexBridge, CodexError
from backend.config import Settings
from backend.web import create_app


def response():
    claim = {'text': 'ForeverUI 可用 /fui 打开设置。', 'provenance': 'verified', 'evidence_ids': ['platform:foreverui']}
    return {'summary': '在主题面板应用亡灵奥术。', 'claims': [claim],
            'actions': [{'title': title, 'reason': claim} for title in ['打开设置', '应用主题', '确认布局']], 'unknowns': []}


def fake_codex(tmp_path, mode='valid'):
    path = tmp_path / 'codex'
    payload = json.dumps(response(), ensure_ascii=False)
    source = f'''#!{sys.executable}
import json,sys,time
from pathlib import Path
args=sys.argv[1:]
if args[:2]==['login','status']:
 print('Logged in using ChatGPT');sys.exit(0)
if {mode!r}=='slow':time.sleep(10)
body=sys.stdin.read()
Path({str(tmp_path / 'call.json')!r}).write_text(json.dumps({{'args':args,'prompt':body}}))
out=Path(args[args.index('--output-last-message')+1])
if {mode!r}=='invalid':out.write_text('not JSON')
elif {mode!r}=='failure':print('private diagnostics must not reach the UI',file=sys.stderr);sys.exit(1)
else:out.write_text({payload!r})
print('{{"type":"turn.completed"}}')
'''
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_codex_reuses_login_and_answers_without_character_snapshot(tmp_path):
    cli = fake_codex(tmp_path)
    advisor = Advisor(Settings(mode='live', data_dir=tmp_path / 'data', ai_provider='codex', codex_command=str(cli)))
    answer, engine = asyncio.run(advisor.generate(None, 'general', '怎么打开奥术主题？'))
    assert engine == 'codex-cli' and answer.summary
    call = json.loads((tmp_path / 'call.json').read_text())
    assert '--ignore-user-config' in call['args'] and '--ephemeral' in call['args']
    assert call['args'][call['args'].index('--sandbox') + 1] == 'read-only'
    assert 'hooks' in call['args'] and 'plugins' in call['args'] and 'shell_tool' in call['args']
    assert 'mcp_servers={}' in call['args'] and 'project_doc_max_bytes=0' in call['args']
    assert not Path(call['args'][call['args'].index('--cd') + 1]).exists(), 'ephemeral files must be removed'


@pytest.mark.parametrize('mode', ['invalid', 'failure'])
def test_codex_protocol_failure_is_sanitized(tmp_path, mode):
    bridge = CodexBridge(str(fake_codex(tmp_path, mode)))
    with pytest.raises(CodexError) as raised:
        asyncio.run(bridge.answer('Answer only', {}, {}))
    assert 'private diagnostics' not in str(raised.value)


def test_codex_timeout_stops_request(tmp_path):
    bridge = CodexBridge(str(fake_codex(tmp_path, 'slow')), timeout=.15)
    with pytest.raises(CodexError, match='超时'):
        asyncio.run(bridge.answer('Answer only', {}, {}))
    assert not (tmp_path / 'call.json').exists()


def test_ask_page_and_endpoint_work_with_codex_before_first_snapshot(tmp_path):
    cli = fake_codex(tmp_path)
    settings = Settings(mode='live', data_dir=tmp_path / 'data', ai_provider='codex', codex_command=str(cli), auto_sync=False)
    with TestClient(create_app(settings), base_url='http://127.0.0.1') as client:
        assert client.get('/api/ai/status').json()['provider'] == 'codex'
        page = client.get('/ask')
        assert page.status_code == 200 and '已登录本机 Codex' in page.text
        assert 'type="submit" disabled' not in page.text
        answer = client.post('/api/ai/ask', json={'question': '如何打开主题？'})
        assert answer.status_code == 200 and answer.json()['engine'] == 'codex-cli'
        rendered = client.post('/ui/ask', data={'question': '如何打开主题？'}, headers={'HX-Request': 'true'})
        assert rendered.status_code == 200 and '本机 Codex' in rendered.text
        assert client.get('/api/snapshots/latest').status_code == 400, 'general questions cannot fabricate a snapshot'
