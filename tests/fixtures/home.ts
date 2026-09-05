/* 首页 Page Object: 公众号列表 + 新增弹窗 + 导入弹窗 */
import { Page, expect } from "@playwright/test";

export class HomePage {
  constructor(private page: Page) {}

  async goto() { await this.page.goto("/"); await this.page.waitForLoadState("networkidle"); }

  async openAddGzh() {
    await this.page.getByRole("button", { name: "新增" }).click();
    await expect(this.page.locator(".ant-modal").last()).toBeVisible();
  }

  /** 新增公众号弹窗: 填名称+biz(弹窗顺序: 链接识别在前, 名称/biz在后); 保存并等弹窗关闭 */
  async fillAdd(name: string, biz: string) {
    const modal = this.page.locator(".ant-modal").last();
    await modal.getByPlaceholder("公众号名称").fill(name);
    await modal.getByPlaceholder("biz 代码").fill(biz);
    await modal.locator("button", { hasText: /保\s*存/ }).last().click();
    // 等关闭动画结束, 遮罩消失后再操作页面
    await expect(this.page.locator(".ant-modal").last()).toBeHidden({ timeout: 8000 });
  }

  rowByName(name: string) {
    return this.page.locator("tr", { hasText: name }).first();
  }

  async expectRow(name: string, visible = true) {
    await expect(this.rowByName(name)).toBeVisible({ visible: !!visible });
  }

  async goArticles(biz: string, name: string) {
    // em 用 Nav: dev 下 router.push(/articles?biz=..&name=..)
    await this.page.evaluate(([b, n]) => {
      (window as any).location.href = `/articles?biz=${encodeURIComponent(b)}&name=${encodeURIComponent(n)}`;
    }, [biz, name] as const);
  }
}