"use client";

import React, { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // original err + friendly hint
  const [err, setErr] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  const [showPassword, setShowPassword] = useState(false);
  const router = useRouter();

  const topBanner = useMemo(() => {
    return "✅ Welcome! This is a Todo App — create an account to start managing your tasks.";
  }, []);

  function setNiceErrors(raw: any) {
    const msg = (raw?.message ?? raw ?? "").toString();

    // keep original error too
    setErr(msg || "Signup failed");

    const lower = msg.toLowerCase();

    // Friendly hints (doesn't change backend behavior)
    if (
      lower.includes("invalid") ||
      lower.includes("incorrect") ||
      lower.includes("bad request") ||
      lower.includes("400")
    ) {
      setHint("Please enter a valid email and a strong password, then try again.");
      return;
    }

    if (
      lower.includes("already") ||
      lower.includes("exists") ||
      lower.includes("taken") ||
      lower.includes("duplicate") ||
      lower.includes("409")
    ) {
      setHint("An account with this email already exists. Please login instead.");
      return;
    }

    setHint("Couldn’t create your account. Please check your details and try again.");
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setHint(null);

    try {
      const data = await api("/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(data.access_token);
      router.push("/dashboard");
    } catch (e: any) {
      setNiceErrors(e);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-100 px-4 py-6">
      <div className="w-full max-w-sm bg-white rounded-xl shadow-md p-5 sm:p-6">
        {/* Top banner */}
        <div className="mb-4 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-800">
          {topBanner}
        </div>

        <h2 className="text-xl sm:text-2xl font-semibold text-center mb-5 sm:mb-6">
          Create Account
        </h2>

        <form onSubmit={onSubmit} className="space-y-4">
          <input
            className="w-full border rounded-lg px-3 py-2 text-sm sm:text-base focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            inputMode="email"
            autoComplete="email"
          />

          {/* Password with eye toggle */}
          <div className="relative">
            <input
              className="w-full border rounded-lg px-3 py-2 pr-11 text-sm sm:text-base focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />

            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-2 text-gray-600 hover:bg-gray-100"
            >
              {/* eye icon */}
              {showPassword ? (
                // eye-off
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M10.6 10.6a2 2 0 0 0 2.8 2.8"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  <path
                    d="M9.9 4.3A10.7 10.7 0 0 1 12 4c7 0 10 8 10 8a18.6 18.6 0 0 1-4.2 5.6"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  <path
                    d="M6.2 6.2A18.6 18.6 0 0 0 2 12s3 8 10 8c1 0 2-.2 3-.5"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  <path
                    d="M3 3l18 18"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              ) : (
                // eye
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M2 12s3.5-8 10-8 10 8 10 8-3.5 8-10 8-10-8-10-8Z"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                  <path
                    d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                </svg>
              )}
            </button>
          </div>

          <button
            type="submit"
            className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 transition text-sm sm:text-base"
          >
            Create account
          </button>

          {/* Friendly hint message */}
          {hint && (
            <p className="text-sm text-center rounded-lg bg-yellow-50 px-3 py-2 text-yellow-800 break-words">
              {hint}{" "}
              {hint.toLowerCase().includes("login") && (
                <a href="/" className="font-semibold underline">
                  Go to Login
                </a>
              )}
            </p>
          )}

          {/* Original error (kept) */}
          {err && (
            <p className="text-red-600 text-sm text-center break-words">
              {err}
            </p>
          )}
        </form>

        <p className="text-center text-sm mt-4">
          Already have an account?{" "}
          <a href="/" className="text-blue-600 hover:underline">
            Login
          </a>
        </p>
      </div>
    </main>
  );
}
