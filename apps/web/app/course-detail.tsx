"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, deleteCourse, getCourse, type CourseDetail } from "./course-api";
import { BackIcon, BookIcon, CloseIcon, FileIcon, RefreshIcon, TrashIcon, UploadIcon } from "./icons";

type LoadState = "loading" | "ready" | "error";

function formatDate(value: string, includeTime = false) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    ...(includeTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(new Date(value));
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export default function CourseDetailView({ courseId }: { courseId: number }) {
  const router = useRouter();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getCourse(courseId, signal);
      setCourse(data);
      setLoadState("ready");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setNotFound(reason instanceof ApiError && reason.status === 404);
      setLoadError(reason instanceof Error ? reason.message : "Unable to load this course.");
      setLoadState("error");
    }
  }, [courseId]);

  useEffect(() => {
    const controller = new AbortController();
    getCourse(courseId, controller.signal)
      .then((data) => {
        setCourse(data);
        setLoadState("ready");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setNotFound(reason instanceof ApiError && reason.status === 404);
        setLoadError(reason instanceof Error ? reason.message : "Unable to load this course.");
        setLoadState("error");
      });
    return () => controller.abort();
  }, [courseId]);

  function retryLoad() {
    setLoadState("loading");
    setLoadError("");
    setNotFound(false);
    void load();
  }

  useEffect(() => {
    if (!showDelete) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deleting) setShowDelete(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [deleting, showDelete]);

  async function handleDelete() {
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteCourse(courseId);
      router.push("/");
      router.refresh();
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : "Unable to delete course.");
      setDeleting(false);
    }
  }

  return (
    <div className="app-page">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="CourseMate home"><span className="brand-mark"><BookIcon width={21} height={21} /></span><span>CourseMate</span></Link>
        <nav className="topnav" aria-label="Main navigation"><Link className="topnav-link active" href="/">Courses</Link></nav>
        <span className="environment-pill"><span className="live-dot" />Local workspace</span>
      </header>

      <main className="page-content detail-content">
        <Link className="back-link" href="/"><BackIcon width={17} height={17} /> All courses</Link>

        {loadState === "loading" && <DetailSkeleton />}

        {loadState === "error" && (
          <section className="state-card error-state detail-error">
            <span className="state-icon error-icon">!</span>
            <h1>{notFound ? "Course not found" : "We couldn't load this course"}</h1>
            <p>{notFound ? "This course may have been deleted or the link is no longer valid." : loadError}</p>
            <div className="state-actions">
              {!notFound && <button className="button secondary" type="button" onClick={retryLoad}><RefreshIcon width={17} height={17} /> Try again</button>}
              <Link className="button primary" href="/">Back to courses</Link>
            </div>
          </section>
        )}

        {loadState === "ready" && course && (
          <>
            <section className="detail-hero">
              <div className="detail-title-row">
                <span className="detail-course-icon"><BookIcon width={28} height={28} /></span>
                <div>
                  <p className="eyebrow">Course workspace</p>
                  <h1>{course.name}</h1>
                  <p className="detail-meta">Created {formatDate(course.created_at)} · {course.documents.length} {course.documents.length === 1 ? "document" : "documents"}</p>
                </div>
              </div>
              <div className="detail-actions">
                <button className="button secondary upload-button" type="button" disabled title="Document upload API is not available yet"><UploadIcon width={18} height={18} /> Upload <span className="coming-soon">Soon</span></button>
                <button className="button danger-ghost" type="button" onClick={() => { setDeleteError(""); setShowDelete(true); }}><TrashIcon width={17} height={17} /> Delete course</button>
              </div>
            </section>

            <section className="documents-section">
              <div className="section-heading">
                <div><h2>Documents</h2><p>Materials connected to this course by the backend.</p></div>
                <span className="count-badge">{course.documents.length}</span>
              </div>

              {course.documents.length === 0 ? (
                <div className="documents-empty">
                  <span className="state-icon"><FileIcon width={27} height={27} /></span>
                  <h3>No documents yet</h3>
                  <p>Document upload is coming next. This course is ready when the API is.</p>
                  <button className="button secondary" type="button" disabled><UploadIcon width={17} height={17} /> Upload coming soon</button>
                </div>
              ) : (
                <div className="document-table-wrap">
                  <table className="document-table">
                    <thead><tr><th>Document</th><th>Status</th><th>Added</th></tr></thead>
                    <tbody>
                      {course.documents.map((document) => (
                        <tr key={document.id}>
                          <td><span className="document-name"><span className="file-tile"><FileIcon width={18} height={18} /></span><span><strong>{document.name}</strong><small>Document #{document.id}</small></span></span></td>
                          <td><span className={`status-chip status-${document.status}`}><span />{statusLabel(document.status)}</span></td>
                          <td className="date-cell">{formatDate(document.created_at, true)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>

      {showDelete && course && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deleting) setShowDelete(false); }}>
          <section className="modal danger-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-description">
            <button className="icon-button modal-close" type="button" aria-label="Close" disabled={deleting} onClick={() => setShowDelete(false)}><CloseIcon /></button>
            <span className="modal-icon danger-icon"><TrashIcon width={24} height={24} /></span>
            <h2 id="delete-title">Delete {course.name}?</h2>
            <p id="delete-description">This permanently removes the course and its document links. This action cannot be undone.</p>
            {deleteError && <p className="form-error" role="alert">{deleteError}</p>}
            <div className="modal-actions">
              <button className="button secondary" type="button" disabled={deleting} onClick={() => setShowDelete(false)}>Cancel</button>
              <button className="button danger" type="button" disabled={deleting} onClick={() => void handleDelete()}>{deleting ? <><span className="spinner light" /> Deleting…</> : "Delete course"}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function DetailSkeleton() {
  return <div className="detail-skeleton" aria-label="Loading course"><div className="skeleton-line short" /><div className="skeleton-line title" /><div className="skeleton-line medium" /><div className="skeleton-panel"><div className="skeleton-line short" /><div className="skeleton-row" /><div className="skeleton-row" /></div></div>;
}