import { useEffect } from 'react'
import './page.css'
import body from './body.html?raw'
import { init } from './logic.js'

// 页面与逻辑由 sync.py 从 ../scripts/index.html 生成，这里只负责挂载；
// 接口仍在 fund.longsizhuo.com（限额、书记员闸都在服务端）
const API = import.meta.env.VITE_API_URL || 'https://fund.longsizhuo.com'

export default function App() {
  // init 往页面里追加按钮、绑事件，同一份 DOM 只能跑一次：QMuse 编辑器预览会把 effect 跑两遍（按钮出现两排）。
  // 用 DOM 上的标记而不是模块变量——真重挂载时 DOM 是新的，仍要重新 init
  useEffect(() => {
    const root = document.getElementById('v-home')
    if (!root || root.dataset.ready) return
    root.dataset.ready = '1'
    init(API)
  }, [])
  return <div dangerouslySetInnerHTML={{ __html: body }} />
}
