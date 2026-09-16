"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, createCourse, deleteCourse, listCourses, type CourseSummary } from "./course-api";
import { ArrowIcon, BookIcon, CloseIcon, PlusIcon, RefreshIcon, TrashIcon } from "./icons";

type LoadState = "loading" | "ready" | "error";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "C";
}

export default function CourseList() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<CourseSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [announcement, setAnnouncement] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await listCourses(signal);
      setCourses(data);
      setLoadState("ready");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setLoadError(reason instanceof Error ? reason.message : "Unable to load courses.");
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    listCourses(controller.signal)
      .then((data) => {
        setCourses(data);
        setLoadState("ready");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setLoadError(reason instanceof Error ? reason.message : "Unable to load courses.");
        setLoadState("error");
      });
    return () => controller.abort();
  }, []);

  function retryLoad() {
    setLoadState("loading");
    setLoadError("");
    void load();
  }

  useEffect(() => {
    if (!showCreate && !deleteTarget) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !creating) setShowCreate(false);
      if (event.key === "Escape" && !deleting) setDeleteTarget(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [creating, deleting, deleteTarget, showCreate]);

  function openCreate() {
    setName("");
    setCreateError("");
    setShowCreate(true);
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setCreateError("Enter a course name to continue.");
      return;
    }

    setCreating(true);
    setCreateError("");
    try {
      const created = await createCourse(normalizedName);
      setCourses((current) => [...current, created]);
      setShowCreate(false);
      setAnnouncement(`${created.name} was created.`);
    } catch (reason) {
      setCreateError(actionError(reason, "Unable to create course."));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;

    setDeleting(true);
    setDeleteError("");
    try {
      await deleteCourse(deleteTarget.id);
      setCourses((current) => current.filter((course) => course.id !== deleteTarget.id));
      setAnnouncement(`${deleteTarget.name} was deleted.`);
      setDeleteTarget(null);
    } catch (reason) {
      setDeleteError(actionError(reason, "Unable to delete course."));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="app-page">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="CourseMate home">
          <span className="brand-mark"><BookIcon width={21} height={21} /></span>
          <span>CourseMate</span>
        </Link>
        <nav className="topnav" aria-label="Main navigation">
          <Link className="topnav-link active" href="/">Courses</Link>
        </nav>
        <span className="environment-pill"><span className="live-dot" />Local workspace</span>
      </header>

      <main className="page-content">
        <section className="page-heading">
          <div>
            <p className="eyebrow">Your learning space</p>
            <h1>Courses</h1>
            <p className="heading-copy">Organize course materials and keep every source in one place.</p>
          </div>
          <button className="button primary" type="button" onClick={openCreate}>
            <PlusIcon width={18} height={18} /> New course
          </button>
        </section>

        <p className="sr-only" role="status" aria-live="polite">{announcement}</p>

        {loadState === "loading" && (
          <section aria-label="Loading courses" className="course-grid">
            {[0, 1, 2].map((item) => <div className="course-card skeleton-card" key={item}><span /><span /><span /></div>)}
          </section>
        )}

        {loadState === "error" && (
          <section className="state-card error-state">
            <span className="state-icon error-icon">!</span>
            <h2>We couldn&apos;t load your courses</h2>
            <p>{loadError}</p>
            <button className="button secondary" type="button" onClick={retryLoad}>
              <RefreshIcon width={17} height={17} /> Try again
            </button>
          </section>
        )}

        {loadState === "ready" && courses.length === 0 && (
          <section className="state-card empty-state">
            <span className="state-icon"><BookIcon width={28} height={28} /></span>
            <h2>Create your first course</h2>
            <p>Start with a course, then add PDF lecture notes, readings, and assignment materials.</p>
            <button className="button primary" type="button" onClick={openCreate}>
              <PlusIcon width={18} height={18} /> New course
            </button>
          </section>
        )}

        {loadState === "ready" && courses.length > 0 && (
          <section className="course-grid" aria-label={`${courses.length} courses`}>
            {courses.map((course, index) => (
              <article className="course-card" key={course.id}>
                <Link className="course-card-link" href={`/courses/${course.id}`} aria-label={`Open ${course.name}`}>
                  <div className={`course-avatar tone-${(index % 4) + 1}`}>{initials(course.name)}</div>
                  <div className="course-card-body">
                    <h2>{course.name}</h2>
                    <p>Created {formatDate(course.created_at)}</p>
                  </div>
                  <span className="course-card-action">Open <ArrowIcon width={17} height={17} /></span>
                </Link>
                <button
                  className="icon-button course-delete"
                  type="button"
                  aria-label={`Delete ${course.name}`}
                  onClick={() => { setDeleteError(""); setDeleteTarget(course); }}
                >
                  <TrashIcon />
                </button>
              </article>
            ))}
          </section>
        )}
      </main>

      {showCreate && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !creating) setShowCreate(false);
        }}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title">
            <button className="icon-button modal-close" type="button" aria-label="Close" disabled={creating} onClick={() => setShowCreate(false)}><CloseIcon /></button>
            <span className="modal-icon"><BookIcon width={24} height={24} /></span>
            <h2 id="create-title">Create a new course</h2>
            <p>Give your course a clear name. You can add documents in the next step.</p>
            <form onSubmit={handleCreate}>
              <label htmlFor="course-name">Course name</label>
              <input
                id="course-name"
                autoFocus
                maxLength={160}
                placeholder="e.g. Introduction to Machine Learning"
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-invalid={Boolean(createError)}
                aria-describedby={createError ? "create-error" : undefined}
                disabled={creating}
              />
              {createError && <p className="form-error" id="create-error" role="alert">{createError}</p>}
              <div className="modal-actions">
                <button className="button secondary" type="button" disabled={creating} onClick={() => setShowCreate(false)}>Cancel</button>
                <button className="button primary" type="submit" disabled={creating}>{creating ? <><span className="spinner" /> Creating…</> : "Create course"}</button>
              </div>
            </form>
          </section>
        </div>
      )}

      {deleteTarget && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !deleting) setDeleteTarget(null);
        }}>
          <section className="modal danger-modal" role="alertdialog" aria-modal="true" aria-labelledby="course-delete-title" aria-describedby="course-delete-description">
            <button className="icon-button modal-close" type="button" aria-label="Close" disabled={deleting} onClick={() => setDeleteTarget(null)}><CloseIcon /></button>
            <span className="modal-icon danger-icon"><TrashIcon width={24} height={24} /></span>
            <h2 id="course-delete-title">Delete {deleteTarget.name}?</h2>
            <p id="course-delete-description">This permanently removes the course and its document links. This action cannot be undone.</p>
            {deleteError && <p className="form-error" role="alert">{deleteError}</p>}
            <div className="modal-actions">
              <button className="button secondary" type="button" disabled={deleting} onClick={() => setDeleteTarget(null)}>Cancel</button>
              <button className="button danger" type="button" disabled={deleting} onClick={() => void handleDelete()}>{deleting ? <><span className="spinner light" /> Deleting…</> : "Delete course"}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function actionError(reason: unknown, fallback: string) {
  if (reason instanceof ApiError) return `Error ${reason.status}: ${reason.message}`;
  return reason instanceof Error ? reason.message : fallback;
}
