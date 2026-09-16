const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CourseSummary = {
  id: number;
  name: string;
  created_at: string;
};

export type DocumentSummary = {
  id: number;
  name: string;
  created_at: string;
  status: string;
};

export type CourseDetail = CourseSummary & {
  documents: DocumentSummary[];
};

type FastApiError = {
  detail?: string | Array<{ msg?: string }>;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(payload: FastApiError | null, fallback: string) {
  if (typeof payload?.detail === "string") return payload.detail;

  if (Array.isArray(payload?.detail)) {
    const message = payload.detail.find((item) => item.msg)?.msg;
    if (message) return message;
  }

  return fallback;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let payload: FastApiError | null = null;
    try {
      payload = (await response.json()) as FastApiError;
    } catch {
      // The API may be unavailable or return a non-JSON proxy response.
    }

    throw new ApiError(
      errorMessage(payload, `Request failed with status ${response.status}`),
      response.status,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listCourses(signal?: AbortSignal) {
  return request<CourseSummary[]>("/courses", { signal });
}

export function createCourse(name: string) {
  return request<CourseSummary>("/courses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function getCourse(courseId: number, signal?: AbortSignal) {
  return request<CourseDetail>(`/courses/${courseId}`, { signal });
}

export function deleteCourse(courseId: number) {
  return request<void>(`/courses/${courseId}`, { method: "DELETE" });
}

export function uploadDocument(courseId: number, file: File) {
  const formData = new FormData();
  formData.append("file", file);

  return request<DocumentSummary>(`/courses/${courseId}/documents`, {
    method: "POST",
    body: formData,
  });
}
