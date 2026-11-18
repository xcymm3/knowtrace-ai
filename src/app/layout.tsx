import type { Metadata } from "next";
import "../../tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "KnowTrace Agent",
  description: "使用模型和本机文件工具完成任务，预览并审批每次文件变更。",
  icons: {
    icon: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
