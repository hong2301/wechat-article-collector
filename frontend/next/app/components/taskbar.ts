// 任务栏控制: 【机制已彻底删除】不再隐藏/恢复任务栏(隐藏会改WorkArea/RECT,
// 导致截图坐标与实际渲染不一致)。保留空函数避免改其它调用点; 调用无任何行为。
export function hideTaskbar() {}
export function showTaskbar() {}
