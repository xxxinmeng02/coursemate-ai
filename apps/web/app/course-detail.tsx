"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, deleteCourse, deleteDocument, getCourse, retryDocument, uploadDocument, type CourseDetail, type DocumentSummary } from "./course-api";
import { createDocumentPolling } from "./document-polling";
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
  if (status === "uploaded") return "Pending processing";
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function hasPendingDocuments(course: CourseDetail | null) {
  return course?.documents.some((document) => document.status === "uploaded" || document.status === "processing") ?? false;
}

function actionError(reason: unknown, fallback: string) {
  if (reason instanceof ApiError) {
    return `Error ${reason.status}: ${reason.message}`;
  }

  return reason instanceof Error ? reason.message : fallback;
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
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState("");
  const [documentToDelete, setDocumentToDelete] = useState<DocumentSummary | null>(null);
  const [documentActions, setDocumentActions] = useState<Record<number, "retry" | "delete">>({});
  const [documentErrors, setDocumentErrors] = useState<Record<number, string>>({});
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState("");
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const courseRef = useRef<CourseDetail | null>(null);
  const pollingRef = useRef<ReturnType<typeof createDocumentPolling> | null>(null);
  const loadControllerRef = useRef<AbortController | null>(null);
  const documentLocksRef = useRef(new Set<number>());
  const uploadingRef = useRef(false);
  const revisionRef = useRef(0);

  const updateCourse = useCallback((data: CourseDetail) => {
    courseRef.current = data;
    setCourse(data);
    if (!hasPendingDocuments(data)) {
      pollingRef.current?.stop();
      setPolling(false);
      setPollError("");
      setPollTimedOut(false);
    }
  }, []);

  const startPolling = useCallback((immediate = false) => {
    setPollError("");
    setPollTimedOut(false);
    setPolling(true);
    pollingRef.current?.restart(immediate);
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getCourse(courseId, signal);
      if (signal?.aborted) return;
      updateCourse(data);
      setLoadState("ready");
      if (hasPendingDocuments(data)) startPolling();
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setNotFound(reason instanceof ApiError && reason.status === 404);
      setLoadError(reason instanceof Error ? reason.message : "Unable to load this course.");
      setLoadState("error");
    }
  }, [courseId, startPolling, updateCourse]);

  useEffect(() => {
    const controller = new AbortController();
    loadControllerRef.current = controller;
    const documentPolling = createDocumentPolling({
      fetch: async (signal) => {
        const revision = revisionRef.current;
        return { data: await getCourse(courseId, signal), revision };
      },
      onData: ({ data, revision }) => {
        // Mutations own their immediate result; a request from before one must
        // not restore a deleted row or overwrite a retry/upload response.
        if (revision === revisionRef.current && !uploadingRef.current && documentLocksRef.current.size === 0) updateCourse(data);
        return hasPendingDocuments(courseRef.current);
      },
      onError: (reason) => {
        setPolling(false);
        setPollError(actionError(reason, "Unable to check document processing."));
      },
      onTimeout: () => {
        setPolling(false);
        setPollTimedOut(true);
      },
    });
    pollingRef.current = documentPolling;
    void load(controller.signal);
    return () => {
      loadControllerRef.current?.abort();
      documentPolling.stop();
      pollingRef.current = null;
    };
  }, [courseId, load, updateCourse]);

  function retryLoad() {
    setLoadState("loading");
    setLoadError("");
    setNotFound(false);
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    void load(controller.signal);
  }

  useEffect(() => {
    if (!showDelete) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deleting) setShowDelete(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [deleting, showDelete]);

  useEffect(() => {
    if (!documentToDelete) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !documentLocksRef.current.has(documentToDelete.id)) setDocumentToDelete(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [documentToDelete]);

  async function handleDocumentAction(document: DocumentSummary, action: "retry" | "delete") {
    if (documentLocksRef.current.has(document.id)) return;
    documentLocksRef.current.add(document.id);
    revisionRef.current++;
    setDocumentActions((current) => ({ ...current, [document.id]: action }));
    setDocumentErrors((current) => ({ ...current, [document.id]: "" }));
    try {
      const result = action === "retry" ? await retryDocument(courseId, document.id) : await deleteDocument(courseId, document.id);
      if (!pollingRef.current) return;
      const current = courseRef.current;
      if (current) updateCourse({
        ...current,
        documents: action === "delete"
          ? current.documents.filter((item) => item.id !== document.id)
          : current.documents.map((item) => item.id === document.id ? result as DocumentSummary : item),
      });
      if (action === "delete") setDocumentToDelete(null);
      else if (hasPendingDocuments(courseRef.current)) startPolling();
    } catch (reason) {
      if (!pollingRef.current) return;
      setDocumentErrors((current) => ({ ...current, [document.id]: actionError(reason, `Unable to ${action} document.`) }));
    } finally {
      revisionRef.current++;
      documentLocksRef.current.delete(document.id);
      if (pollingRef.current) {
        setDocumentActions((current) => {
          const next = { ...current };
          delete next[document.id];
          return next;
        });
      }
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteCourse(courseId);
      if (!pollingRef.current) return;
      router.push("/");
      router.refresh();
    } catch (reason) {
      if (!pollingRef.current) return;
      setDeleteError(actionError(reason, "Unable to delete course."));
      setDeleting(false);
    }
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || uploadingRef.current) return;

    uploadingRef.current = true;
    revisionRef.current++;
    setUploading(true);
    setUploadError("");
    setUploadSuccess("");

    try {
      const document = await uploadDocument(courseId, file);
      if (!pollingRef.current) return;
      const current = courseRef.current;
      if (current) updateCourse({ ...current, documents: [...current.documents, document] });
      setUploadSuccess(`${document.name} was uploaded successfully.`);
      if (hasPendingDocuments(courseRef.current)) startPolling();
    } catch (reason) {
      if (!pollingRef.current) return;
      if (reason instanceof ApiError && reason.status === 404) {
        pollingRef.current?.stop();
        courseRef.current = null;
        setPolling(false);
        setCourse(null);
        setNotFound(true);
        setLoadError(reason.message);
        setLoadState("error");
      } else {
        setUploadError(actionError(reason, "Unable to upload document."));
      }
    } finally {
      uploadingRef.current = false;
      revisionRef.current++;
      if (pollingRef.current) setUploading(false);
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
                <input
                  ref={fileInputRef}
                  className="sr-only"
                  type="file"
                  accept="application/pdf,.pdf"
                  aria-label="Choose a PDF to upload"
                  onChange={(event) => void handleUpload(event)}
                  disabled={uploading}
                />
                <button
                  className="button secondary upload-button"
                  type="button"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? <><span className="spinner" /> Uploading…</> : <><UploadIcon width={18} height={18} /> Upload PDF</>}
                </button>
                <button className="button danger-ghost" type="button" onClick={() => { setDeleteError(""); setShowDelete(true); }}><TrashIcon width={17} height={17} /> Delete course</button>
              </div>
            </section>

            {(uploadError || uploadSuccess) && (
              <p className={uploadError ? "upload-message upload-error" : "upload-message upload-success"} role={uploadError ? "alert" : "status"}>
                {uploadError || uploadSuccess}
              </p>
            )}

            <section className="documents-section">
              <div className="section-heading">
                <div><h2>Documents</h2><p>Materials connected to this course by the backend.</p></div>
                <span className="count-badge">{course.documents.length}</span>
              </div>

              {(polling || pollError || pollTimedOut) && (
                <div className={`processing-message${pollError ? " upload-error" : ""}`} role={pollError ? "alert" : "status"}>
                  <p>{pollError
                    ? `Document status checks stopped. ${pollError}`
                    : pollTimedOut
                      ? "Status checks paused after two minutes. Pending documents may need a retry if processing has not started."
                      : "Checking processing every 3 seconds for up to 2 minutes. Pending documents are waiting for processing to start."}</p>
                  {!polling && <button className="button secondary" type="button" onClick={() => startPolling(true)}><RefreshIcon width={16} height={16} /> Resume status checks</button>}
                </div>
              )}

              {course.documents.length === 0 ? (
                <div className="documents-empty">
                  <span className="state-icon"><FileIcon width={27} height={27} /></span>
                  <h3>No documents yet</h3>
                  <p>Upload a PDF to add lecture notes, readings, or assignment material to this course.</p>
                  <button className="button secondary" type="button" disabled={uploading} onClick={() => fileInputRef.current?.click()}><UploadIcon width={17} height={17} /> Choose PDF</button>
                </div>
              ) : (
                <div className="document-table-wrap">
                  <table className="document-table">
                    <thead><tr><th>Document</th><th>Status</th><th>Added</th><th>Actions</th></tr></thead>
                    <tbody>
                      {course.documents.map((document) => (
                        <tr key={document.id}>
                          <td><span className="document-name"><span className="file-tile"><FileIcon width={18} height={18} /></span><span><strong>{document.name}</strong><small>Document #{document.id}</small></span></span></td>
                          <td><span className={`status-chip status-${document.status}`}><span />{statusLabel(document.status)}</span></td>
                          <td className="date-cell">{formatDate(document.created_at, true)}</td>
                          <td>
                            <div className="document-actions">
                              {(document.status === "failed" || document.status === "uploaded") && <button className="button secondary" type="button" disabled={!!documentActions[document.id]} onClick={() => void handleDocumentAction(document, "retry")} aria-label={`Retry ${document.name}`}><RefreshIcon width={15} height={15} />{documentActions[document.id] === "retry" ? "Retrying…" : "Retry"}</button>}
                              <button className="button danger-ghost" type="button" disabled={!!documentActions[document.id]} onClick={() => { setDocumentErrors((current) => ({ ...current, [document.id]: "" })); setDocumentToDelete(document); }} aria-label={`Delete ${document.name}`}><TrashIcon width={15} height={15} />{documentActions[document.id] === "delete" ? "Deleting…" : "Delete"}</button>
                            </div>
                            {documentErrors[document.id] && <p className="document-action-error" role="alert">{documentErrors[document.id]}</p>}
                          </td>
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

      {documentToDelete && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !documentActions[documentToDelete.id]) setDocumentToDelete(null); }}>
          <section className="modal danger-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-document-title" aria-describedby="delete-document-description">
            <button className="icon-button modal-close" type="button" aria-label="Close" disabled={!!documentActions[documentToDelete.id]} onClick={() => setDocumentToDelete(null)}><CloseIcon /></button>
            <span className="modal-icon danger-icon"><TrashIcon width={24} height={24} /></span>
            <h2 id="delete-document-title">Delete {documentToDelete.name}?</h2>
            <p id="delete-document-description">This removes this document from the course. Stored material is cleaned up when no courses still reference it.</p>
            {documentErrors[documentToDelete.id] && <p className="form-error" role="alert">{documentErrors[documentToDelete.id]}</p>}
            <div className="modal-actions">
              <button className="button secondary" type="button" disabled={!!documentActions[documentToDelete.id]} onClick={() => setDocumentToDelete(null)}>Cancel</button>
              <button className="button danger" type="button" disabled={!!documentActions[documentToDelete.id]} onClick={() => void handleDocumentAction(documentToDelete, "delete")}>{documentActions[documentToDelete.id] ? <><span className="spinner light" /> Deleting…</> : "Delete document"}</button>
            </div>
          </section>
        </div>
      )}

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
