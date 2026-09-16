import { notFound } from "next/navigation";
import CourseDetailView from "@/app/course-detail";

export default async function CourseDetailPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;

  if (!/^\d+$/.test(courseId) || Number(courseId) < 1) {
    notFound();
  }

  return <CourseDetailView courseId={Number(courseId)} />;
}
