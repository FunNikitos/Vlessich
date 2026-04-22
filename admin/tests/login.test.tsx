import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginPage } from "@/pages/Login";
import { AuthProvider } from "@/hooks/useAuth";

const FETCH = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", FETCH);
  sessionStorage.clear();
  FETCH.mockReset();
});

function renderLogin() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div>HOME</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jwtWithExp(exp: number): string {
  const payload = btoa(
    JSON.stringify({ sub: "u", role: "superadmin", iat: 0, exp }),
  )
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `h.${payload}.s`;
}

describe("LoginPage", () => {
  it("renders email + password inputs", () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeDefined();
    expect(screen.getByLabelText(/password/i)).toBeDefined();
  });

  it("shows error on 401", async () => {
    FETCH.mockResolvedValueOnce(
      new Response(JSON.stringify({ code: "bad_credentials", message: "nope" }), {
        status: 401,
      }),
    );
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toBeDefined();
  });

  it("navigates home on success", async () => {
    FETCH.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: jwtWithExp(9999999999),
          role: "superadmin",
        }),
        { status: 200 },
      ),
    );
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
    await userEvent.type(screen.getByLabelText(/password/i), "pw");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("HOME")).toBeDefined();
  });
});
