import type { Metadata } from "next";
import "../../tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "KnowTrace AI｜可追溯知识工作台",
  description: "基于项目资料提供带来源依据的 AI 问答与结构化结论。",
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
