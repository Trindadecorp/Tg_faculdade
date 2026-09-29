import "./globals.css";

export const metadata = {
  title: "PhishGuard BR",
  description: "Detecção de phishing por e-mail com contexto brasileiro",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
