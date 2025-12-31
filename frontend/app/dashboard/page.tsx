"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { clearToken } from "@/lib/auth";
import { useRouter } from "next/navigation";

type Todo = {
  id: number;
  title: string;
  description?: string | null;
  completed: boolean;
};

export default function DashboardPage() {
  const router = useRouter();

  const [todos, setTodos] = useState<Todo[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // edit states
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");

  // selection state (checkboxes)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const selectedCount = selectedIds.size;

  const allSelected = useMemo(() => {
    return todos.length > 0 && selectedIds.size === todos.length;
  }, [todos.length, selectedIds]);

  // mobile menu
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  /* ---------------- LOAD TODOS ---------------- */
  async function loadTodos() {
    setErr(null);
    try {
      setLoading(true);
      const data = await api("/todos");
      setTodos(data);

      // remove selections that no longer exist
      setSelectedIds((prev) => {
        const next = new Set<number>();
        const ids = new Set<number>(data.map((t: Todo) => t.id));
        for (const id of prev) {
          if (ids.has(id)) next.add(id);
        }
        return next;
      });
    } catch (e: any) {
      setErr(e.message ?? "Failed to load todos");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTodos();
  }, []);

  // close mobile menu on outside click / Escape
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuOpen) return;
      const target = e.target as Node;
      if (menuRef.current && !menuRef.current.contains(target)) {
        setMenuOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (!menuOpen) return;
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  /* ---------------- ADD TODO ---------------- */
  async function addTodo() {
    setErr(null);
    try {
      await api("/todos", {
        method: "POST",
        body: JSON.stringify({
          title,
          description: description || null,
        }),
      });

      setTitle("");
      setDescription("");
      loadTodos();
    } catch (e: any) {
      setErr(e.message ?? "Failed to add todo");
    }
  }

  /* ---------------- TOGGLE COMPLETE ---------------- */
  async function toggleComplete(todo: Todo) {
    setErr(null);
    try {
      await api(`/todos/${todo.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          completed: !todo.completed,
        }),
      });
      loadTodos();
    } catch (e: any) {
      setErr(e.message ?? "Failed to update todo");
    }
  }

  /* ---------------- UPDATE TODO ---------------- */
  async function updateTodo(id: number) {
    setErr(null);
    try {
      await api(`/todos/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: editTitle,
          description: editDescription || null,
        }),
      });

      setEditingId(null);
      loadTodos();
    } catch (e: any) {
      setErr(e.message ?? "Failed to update todo");
    }
  }

  /* ---------------- DELETE SINGLE TODO ---------------- */
  async function deleteTodo(id: number) {
    const ok = window.confirm("Are you sure you want to delete this todo?");
    if (!ok) return;

    setErr(null);
    try {
      await api(`/todos/${id}`, { method: "DELETE" });

      // remove from selection too
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });

      loadTodos();
    } catch (e: any) {
      setErr(e.message ?? "Failed to delete todo");
    }
  }

  /* ---------------- DELETE SELECTED ---------------- */
  async function deleteSelected() {
    if (selectedIds.size === 0) return;

    const ok = window.confirm(`Delete selected (${selectedIds.size}) todo(s)?`);
    if (!ok) return;

    try {
      setErr(null);
      setLoading(true);

      const ids = Array.from(selectedIds);
      await Promise.all(ids.map((id) => api(`/todos/${id}`, { method: "DELETE" })));

      setSelectedIds(new Set());
      await loadTodos();
    } catch (e: any) {
      setErr(e.message ?? "Failed to delete selected todos");
    } finally {
      setLoading(false);
    }
  }

  /* ---------------- DELETE ALL ---------------- */
  async function deleteAll() {
    if (todos.length === 0) return;

    const ok = window.confirm(`Delete ALL (${todos.length}) todo(s)?`);
    if (!ok) return;

    try {
      setErr(null);
      setLoading(true);

      const ids = todos.map((t) => t.id);
      await Promise.all(ids.map((id) => api(`/todos/${id}`, { method: "DELETE" })));

      setSelectedIds(new Set());
      await loadTodos();
    } catch (e: any) {
      setErr(e.message ?? "Failed to delete all todos");
    } finally {
      setLoading(false);
    }
  }

  /* ---------------- CHECKBOX HELPERS ---------------- */
  function toggleSelectOne(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelectedIds((prev) => {
      if (todos.length === 0) return prev;

      // if all selected -> clear, else select all
      if (prev.size === todos.length) return new Set();
      return new Set(todos.map((t) => t.id));
    });
  }

  /* ---------------- LOGOUT ---------------- */
  async function logout() {
    const ok = window.confirm("Do you want to logout?");
    if (!ok) return;

    try {
      await api("/auth/logout", { method: "POST" });
    } catch {}

    clearToken();
    router.push("/");
  }

  function goChat() {
    setMenuOpen(false);
    router.push("/chat");
  }

  async function doLogout() {
    setMenuOpen(false);
    await logout();
  }

  /* ---------------- UI ---------------- */
  return (
    <main className="min-h-screen bg-gray-100 p-4 sm:p-6">
      <div className="mx-auto w-full max-w-2xl rounded-xl bg-white p-4 sm:p-6 shadow">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between gap-3">
          <h1 className="text-xl sm:text-2xl font-bold text-gray-800">Dashboard</h1>

          {/* Desktop buttons */}
          <div className="hidden sm:flex gap-2">
            <button
              onClick={() => router.push("/chat")}
              className="rounded-lg bg-blue-500 px-3 py-1.5 text-sm text-white hover:bg-blue-600"
            >
              Chatbot
            </button>

            <button
              onClick={logout}
              className="rounded-lg bg-red-500 px-3 py-1.5 text-sm text-white hover:bg-red-600"
            >
              Logout
            </button>
          </div>

          {/* Mobile hamburger */}
          <div className="relative sm:hidden" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Open menu"
              aria-expanded={menuOpen}
              className="inline-flex items-center justify-center rounded-lg border bg-white px-3 py-2 text-gray-700 hover:bg-gray-50"
            >
              {/* simple hamburger icon */}
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M4 6h16M4 12h16M4 18h16"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>

            {menuOpen && (
              <div className="absolute right-0 mt-2 w-44 overflow-hidden rounded-lg border bg-white shadow-lg">
                <button
                  onClick={goChat}
                  className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                >
                  Chatbot
                </button>
                <button
                  onClick={doLogout}
                  className="block w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                >
                  Logout
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Add Todo */}
        <div className="mb-5 space-y-2">
          <input
            placeholder="Todo title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border px-3 py-2 text-sm"
          />

          <textarea
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full rounded-lg border px-3 py-2 text-sm"
          />

          <button
            onClick={addTodo}
            disabled={!title.trim()}
            className="w-full rounded-lg bg-green-500 py-2 text-sm text-white hover:bg-green-600 disabled:bg-gray-300"
          >
            Add Todo
          </button>
        </div>

        {err && <p className="mb-4 text-sm text-red-500">{err}</p>}

        {/* Bulk Actions */}
        <div className="mb-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleSelectAll}
              disabled={todos.length === 0}
            />
            Select All
          </label>

          <div className="flex flex-col sm:flex-row gap-2 sm:justify-end">
            <button
              onClick={deleteSelected}
              disabled={selectedCount === 0 || loading}
              className="w-full sm:w-auto rounded-lg bg-orange-500 px-3 py-1.5 text-sm text-white hover:bg-orange-600 disabled:bg-gray-300"
            >
              Delete Selected {selectedCount > 0 ? `(${selectedCount})` : ""}
            </button>

            <button
              onClick={deleteAll}
              disabled={todos.length === 0 || loading}
              className="w-full sm:w-auto rounded-lg bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700 disabled:bg-gray-300"
            >
              Delete All
            </button>
          </div>
        </div>

        {/* Todo List */}
        {loading ? (
          <p className="text-center text-sm text-gray-500">Loading...</p>
        ) : (
          <ul className="space-y-2">
            {todos.map((todo) => (
              <li key={todo.id} className="rounded-lg border p-3">
                {editingId === todo.id ? (
                  <>
                    <input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="mb-2 w-full rounded border px-2 py-1 text-sm"
                    />

                    <textarea
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={2}
                      className="mb-2 w-full rounded border px-2 py-1 text-sm"
                    />

                    <div className="flex flex-col sm:flex-row gap-2">
                      <button
                        onClick={() => updateTodo(todo.id)}
                        className="rounded bg-blue-500 px-3 py-2 sm:py-1 text-sm text-white"
                      >
                        Update
                      </button>

                      <button
                        onClick={() => setEditingId(null)}
                        className="rounded bg-gray-300 px-3 py-2 sm:py-1 text-sm"
                      >
                        Cancel
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                      <div className="flex items-start sm:items-center gap-2 min-w-0">
                        {/* selection checkbox */}
                        <input
                          type="checkbox"
                          checked={selectedIds.has(todo.id)}
                          onChange={() => toggleSelectOne(todo.id)}
                          title="Select for bulk delete"
                          className="mt-1 sm:mt-0"
                        />

                        {/* Complete / Incomplete toggle button */}
                        <button
                          onClick={() => toggleComplete(todo)}
                          className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${
                            todo.completed
                              ? "bg-green-100 text-green-700"
                              : "bg-gray-200 text-gray-700"
                          }`}
                          title="Toggle complete"
                        >
                          {todo.completed ? "Completed" : "Mark Complete"}
                        </button>

                        <span
                          className={`text-sm font-medium break-words ${
                            todo.completed
                              ? "line-through text-gray-400"
                              : "text-gray-800"
                          }`}
                        >
                          {todo.title}
                        </span>
                      </div>

                      <div className="flex gap-3 sm:justify-end">
                        <button
                          onClick={() => {
                            setEditingId(todo.id);
                            setEditTitle(todo.title);
                            setEditDescription(todo.description || "");
                          }}
                          className="text-sm text-blue-500"
                        >
                          Edit
                        </button>

                        <button
                          onClick={() => deleteTodo(todo.id)}
                          className="text-sm text-red-500"
                        >
                          Delete
                        </button>
                      </div>
                    </div>

                    {todo.description && (
                      <p className="mt-1 text-sm text-gray-500 break-words">
                        {todo.description}
                      </p>
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
