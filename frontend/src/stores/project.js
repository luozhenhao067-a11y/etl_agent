import { reactive } from 'vue'

// 当前项目上下文。项目选择/成员与角色分配接口未定义（待确认 P-22），
// 演示固定使用合成项目 prj_demo_001（契约示例 ID，不对应真实资源）。

const state = reactive({
  projectId: 'prj_demo_001',
  name: '订单数据集成（演示项目）',
  env: 'prod',
})

export function useProjectStore() {
  return { state }
}
