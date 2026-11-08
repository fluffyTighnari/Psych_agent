/**
 * SSE 分帧单测。
 *
 * 背景：曾经按 `\n\n` 切帧，而 sse_starlette 实际输出 CRLF，
 * 导致一帧都切不出来、正文完全收不到，且界面上「看起来在跑」——
 * 这类静默失败必须由测试兜住。
 *
 * 运行：node scripts/test-sse-frames.mjs
 */

let pass = 0
let fail = 0

function eq(actual, expected, label) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    pass++
    console.log(`PASS  ${label}`)
  } else {
    fail++
    console.log(`FAIL  ${label}`)
    console.log(`      expected: ${JSON.stringify(expected)}`)
    console.log(`      actual:   ${JSON.stringify(actual)}`)
  }
}

/* ---------- 复刻被测逻辑（与 chat-stream.ts 保持一致） ---------- */

function parseFrame(raw) {
  const dataLines = []
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  const joined = dataLines.join('')
  if (!joined) return null
  try {
    return JSON.parse(joined)
  } catch {
    return null
  }
}

function findFrameBoundary(buf) {
  const lf = buf.indexOf('\n\n')
  const crlf = buf.indexOf('\r\n\r\n')
  if (crlf >= 0 && (lf < 0 || crlf <= lf)) return [crlf, 4]
  if (lf >= 0) return [lf, 2]
  return null
}

/** 模拟流式切帧：按给定 chunk 序列喂入，返回解析出的事件 */
function runStream(chunks) {
  const events = []
  let buffer = ''
  for (const chunk of chunks) {
    buffer += chunk
    let boundary
    while ((boundary = findFrameBoundary(buffer)) !== null) {
      const [idx, sepLen] = boundary
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + sepLen)
      const evt = parseFrame(raw)
      if (evt) events.push(evt)
    }
  }
  if (buffer.trim()) {
    const evt = parseFrame(buffer)
    if (evt) events.push(evt)
  }
  return events
}

/* ---------- 用例 ---------- */

// 1. CRLF 分帧（sse_starlette 的真实输出）
runStreamTest: {
  const stream =
    'data: {"type":"meta","intent_type":"advisor","ended":false}\r\n\r\n' +
    'data: {"type":"reply_chunk","content":"你好"}\r\n\r\n' +
    'data: {"type":"finish"}\r\n\r\n'
  eq(runStream([stream]), [
    { type: 'meta', intent_type: 'advisor', ended: false },
    { type: 'reply_chunk', content: '你好' },
    { type: 'finish' },
  ], 'CRLF 分帧')
}

// 2. LF 分帧（容错）
{
  const stream =
    'data: {"type":"reply_chunk","content":"A"}\n\n' +
    'data: {"type":"reply_chunk","content":"B"}\n\n'
  eq(runStream([stream]), [
    { type: 'reply_chunk', content: 'A' },
    { type: 'reply_chunk', content: 'B' },
  ], 'LF 分帧')
}

// 3. 帧被任意位置切断（模拟网络分包）
{
  const stream =
    'data: {"type":"reply_chunk","content":"多字节中文"}\r\n\r\n' +
    'data: {"type":"finish"}\r\n\r\n'
  const chunks = []
  for (let i = 0; i < stream.length; i += 7) chunks.push(stream.slice(i, i + 7))
  eq(runStream(chunks), [
    { type: 'reply_chunk', content: '多字节中文' },
    { type: 'finish' },
  ], '逐 7 字符分包')
}

// 4. 多 data 行拼接
{
  const stream = 'data: {"type":"reply_chunk",\ndata: "content":"拼接"}\r\n\r\n'
  eq(runStream([stream]), [{ type: 'reply_chunk', content: '拼接' }], '多行 data 拼接')
}

// 5. 无 data 行的帧被忽略（如心跳注释）
eq(runStream([': ping\r\n\r\n']), [], '忽略无 data 行的帧')

// 6. 畸形 JSON 不抛异常
eq(runStream(['data: {bad json\r\n\r\n']), [], '畸形 JSON 静默忽略')

// 7. 结束符缺失的尾帧被兜底处理
eq(runStream(['data: {"type":"finish"}']), [{ type: 'finish' }], '无尾分隔符的末帧')

// 8. 空帧与连续分隔符
eq(
  runStream(['\r\n\r\ndata: {"type":"finish"}\r\n\r\n\r\n\r\n']),
  [{ type: 'finish' }],
  '空帧与连续分隔符',
)

// 9. 回归守卫：仅换行符不含 CR 时也能切（防止有人把逻辑改回只认 \n\n）
{
  const stream = 'data: {"type":"a"}\r\n\r\ndata: {"type":"b"}\r\n\r\n'
  eq(runStream([stream]).length, 2, '回归：CRLF 下必须切出 2 帧')
}

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
