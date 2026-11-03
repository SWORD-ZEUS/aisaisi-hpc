// 爱赛思公开前端帧协议的草案：认证数据仅从标准输入取得，不输出连接地址。
// Node.js 24 的原生 WebSocket（双向通信协议）；不读取浏览器或凭据文件。
let input = '';
for await (const chunk of process.stdin) {
  input += chunk.toString('utf8');
  if (input.length > 1024 * 1024) throw new Error('输入超过限制');
}
let config;
try { config = JSON.parse(input); }
catch { process.stdout.write(JSON.stringify({ok: false, error: '传输配置不是可解析的JSON（JavaScript对象表示法）'})); process.exit(2); }
const hidden = value => String(value).split(String(config.token || '')).join('[已隐藏]');
const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
let finished = false, socket, timer;
function finish(reply) {
  if (finished) return;
  finished = true;
  if (timer) clearTimeout(timer);
  try { socket?.close(); } catch {}
  process.stdout.write(JSON.stringify(reply), () => process.exit(reply.ok ? 0 : 2));
}
try {
  const origin = new URL(config.origin);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash)
    throw new Error('站点必须为HTTPS（加密超文本传输协议）地址且不含账号、路径或查询参数');
  if (typeof config.token !== 'string' || !config.token || /[\r\n\x00]/.test(config.token))
    throw new Error('显式访问令牌不可用');
  if (!Number.isSafeInteger(config.project) || config.project < 1 || !Number.isSafeInteger(config.timeout) || config.timeout < 1)
    throw new Error('项目编号或等待时间不正确');
  if (typeof config.command !== 'string' || !config.command.trim()) throw new Error('需要明确的终端命令');
  if (typeof WebSocket !== 'function') throw new Error('当前Node.js没有原生WebSocket（双向通信协议）');
  const url = new URL('/hpc-portal/pod/v1/TerminalWs', origin);
  url.protocol = 'wss:';
  url.searchParams.set('token', config.token);
  url.searchParams.set('X-GW-CUR-PID', String(config.project));
  const nonce = crypto.randomUUID().replaceAll('-', '');
  const start = '__AISASI_START_' + nonce + '__';
  const end = '__AISASI_DONE_' + nonce + '__';
  const wrapper = "printf '\\n%s\\n' " + quote(start) + '; bash -c ' + quote(config.command) +
    "; _aisasi_rc=$?; printf '\\n%s:%s\\n' " + quote(end) + ' "$_aisasi_rc"\r';
  const decoder = new TextDecoder('utf-8');
  let received = '', sent = false;
  socket = new WebSocket(url);
  socket.binaryType = 'arraybuffer';
  timer = setTimeout(() => finish({ok: false, error: '终端等待超时；远端命令可能继续，未确认完成，未自动重试'}), config.timeout * 1000);
  socket.addEventListener('open', () => {
    socket.send(JSON.stringify({type: 'resize', cols: config.cols || 160, rows: config.rows || 48}));
  });
  socket.addEventListener('message', event => {
    if (finished) return;
    let output = '';
    if (event.data instanceof ArrayBuffer) output = decoder.decode(event.data, {stream: true});
    else if (typeof event.data === 'string') {
      try {
        const message = JSON.parse(event.data);
        if (message?.message) {
          // 与前端一致：结构化消息是状态，不当作程序输出或完成证明。
          return;
        }
      } catch { output = event.data; }
    }
    if (!output) return;
    received += output;
    if (received.length > 2 * 1024 * 1024) {
      finish({ok: false, error: '终端输出超过2 MiB（兆字节）；远端程序是否继续需另行查询'});
      return;
    }
    if (!sent) {
      socket.send(JSON.stringify({type: 'command', data: wrapper}));
      sent = true;
    }
    const plain = received.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '');
    const startAt = plain.indexOf('\n' + start + '\r\n') >= 0 ? plain.indexOf('\n' + start + '\r\n') : plain.indexOf('\n' + start + '\n');
    if (startAt < 0) return;
    const afterStart = plain.indexOf('\n', startAt + 1 + start.length) + 1;
    const body = plain.slice(afterStart);
    const match = new RegExp('(?:^|\\r?\\n)' + end + ':([0-9]+)(?:\\r?\\n|$)').exec(body);
    if (match) {
      finish({ok: true, exit_code: Number(match[1]), stdout: hidden(body.slice(0, match.index).replaceAll('\r\n', '\n'))});
    }
  });
  socket.addEventListener('error', () => finish({ok: false, error: 'WebSocket（双向通信协议）连接失败；未打印含令牌的地址，未自动重试'}));
  socket.addEventListener('close', () => {
    if (!finished) finish({ok: false, error: '终端连接已关闭；未确认命令返回状态，未自动重连或重试'});
  });
} catch {
  // 异常原文可能含带令牌地址，禁止直接输出。
  finish({ok: false, error: '终端传输配置或连接失败；未输出认证信息，未执行自动重试'});
}
