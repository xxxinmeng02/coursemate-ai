import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const baseProps: IconProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
};

export function PlusIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="M12 5v14M5 12h14" /></svg>;
}

export function ArrowIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="m9 18 6-6-6-6" /></svg>;
}

export function BackIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="m15 18-6-6 6-6" /><path d="M9 12h10" /></svg>;
}

export function BookIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></svg>;
}

export function FileIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /></svg>;
}

export function UploadIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M20 15v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4" /></svg>;
}

export function TrashIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="m19 6-1 14H6L5 6" /><path d="M10 11v5M14 11v5" /></svg>;
}

export function RefreshIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="M20 7h-5V2" /><path d="M20 7a8 8 0 1 0 1 7" /></svg>;
}

export function CloseIcon(props: IconProps) {
  return <svg {...baseProps} {...props}><path d="m18 6-12 12M6 6l12 12" /></svg>;
}