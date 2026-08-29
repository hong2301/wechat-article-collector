/* 冒烟: dev 浏览器 + 后端健康/日志基线
   跑法: npx playwright test --project=dev-browser
   标注 @dev/@all 会分别进入对应 project */
import { expect, test } from "@playwright/test";
import { HomePage } from "../../fixtures/home";
import { api, assertLogClean } from "../../utils/e2e";

test.describe("后端连通 + 日志基线", () => {
  test("@all 后端 /api/health 正常", async () => {
    // api() 已断言 2xx; 再确认 JSON 可解析
    const d = await api("/api/health");
    expect(typeof d).toBe("object");
  });

  test("@all 公众号列表接口可返回", async () => {
    const d = await api("/api/accounts?page=1&page_size=5");
    expect(d).toHaveProperty("items");
  });
});

test.describe("首页 UI 冒烟", () => {
  test("@dev 首页能打开并显示公众号列表", async ({ page }) => {
    const home = new HomePage(page);
    home.goto();
    await expect(page.getByText("微信公众号采集器")).toBeVisible();
    await expect(page.locator("table").first()).toBeVisible();
  });

  test("@dev 新增公众号后列表出现该行(唯一标识, 用例结束清理)",
  async ({ page }) => {
    const stamp = Date.now().toString().slice(-8);
    const gzh = `__e2e_${stamp}`;
    const biz = `__e2e${stamp}__`;
    const home = new HomePage(page);
    await home.goto();
    await home.openAddGzh();
    await home.fillAdd(gzh, biz);
    await home.expectRow(gzh);
    // 清理: 删除测试行(删除有确认弹窗, 点确认)
    const row = await home.rowByName(gzh);
    await row.getByRole("button", { name: "删除" }).click();
    await page.locator(".ant-modal").last()
      .locator("button", { hasText: /确\s*认/ }).last().click();
    await expect(row).toBeHidden();
  });

  test("@dev 本轮操作后后端日志无异常(Traceback)", async () => {
    // 只查本轮(测试启动后)的新增日志段
    const fs = require("fs");
    const base = fs.existsSync("e2e/.baseline")
      ? Number(fs.readFileSync("e2e/.baseline", "utf8")) : 0;
    await assertLogClean(base);
  });
});