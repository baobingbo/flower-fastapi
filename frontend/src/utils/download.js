/**
 * 触发浏览器下载一个 Blob（导出 CSV/JSON 等文件接口返回的二进制内容）。
 * @param {Blob|ArrayBuffer|BlobPart[]} data axios responseType:'blob' 返回的内容
 * @param {string} filename 下载文件名（含扩展名）
 */
export function downloadBlob(data, filename) {
  const blob = data instanceof Blob ? data : new Blob([data])
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 延迟释放，确保下载已启动
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 生成含时间戳的文件名：tasks-20260823-143000.csv */
export function stampName(base, ext) {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const stamp =
    d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) +
    '-' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds())
  return base + '-' + stamp + '.' + ext
}
