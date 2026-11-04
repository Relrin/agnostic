// Roles & permissions against a stubbed control plane: the Operator edit (+knowledge:write, −approvals:delete) shows
// its token-scope diff and who gets it, then saves with the version it was edited from.
import { expect, test } from "@playwright/test";

import { stubRoles } from "./fixtures/roles";
import { stubApi } from "./stubs";

test("roles: the Operator edit shows its scope diff and saves with the version", async ({ page }) => {
  await stubApi(page);
  const roles = await stubRoles(page);
  await page.goto("/access/roles?role=rol_operator");

  await expect(page.getByRole("heading", { name: "Roles & permissions", level: 1 })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Roles" });
  await expect(nav.getByRole("link", { name: "Operator, 9 people" })).toHaveAttribute("aria-current", "page");
  const matrix = page.getByRole("table", { name: "Operator permissions" });
  const knowledgeWrite = matrix.getByRole("checkbox", { name: "Operator: knowledge write" });
  const approvalsDelete = matrix.getByRole("checkbox", { name: "Operator: approvals delete" });
  await expect(knowledgeWrite).not.toBeChecked();
  await expect(approvalsDelete).toBeChecked();

  await knowledgeWrite.check();
  await approvalsDelete.uncheck();
  const bar = page.getByRole("region", { name: "Save changes" });
  await expect(bar).toContainText("2 unsaved changes");

  const aside = page.getByRole("complementary", { name: "Token scopes" });
  const changes = aside.getByRole("list", { name: "Scope changes" });
  await expect(changes).toContainText("knowledge:write");
  await expect(changes).toContainText("approvals:delete");
  await expect(aside.getByLabel("21 scopes")).toBeVisible();
  await expect(aside).toContainText(
    "9 people and 2 groups (Support AI, Billing ops) get the new scopes on their next request.",
  );
  await expect(aside).toContainText("No redeploy.");

  await bar.getByRole("button", { name: "Save role" }).click();
  await expect(bar).toContainText("All changes saved");
  expect(roles.saved).toHaveLength(1);
  expect(roles.saved[0]?.version).toBe(4);
  expect(roles.saved[0]?.permissions.knowledge).toEqual(["read", "write"]);
  expect(roles.saved[0]?.permissions.approvals).toEqual(["read", "write"]);
  await expect(page.getByRole("button", { name: "Version 5" })).toBeVisible();
});
