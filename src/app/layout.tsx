import type { Metadata } from "next";
import "../../tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "CommerceLens AI｜电商选品与竞品调研",
  description: "以可追溯资料支持电商选品、竞品对比与卖点策略决策。",
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
