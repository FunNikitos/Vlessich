import { QRCodeSVG } from "qrcode.react";

interface QRCodeBlockProps {
  value: string;
  size?: number;
}

/** White-bg QR card per Design.txt rule: QR is "content" (album-art exception). */
export function QRCodeBlock({ value, size = 200 }: QRCodeBlockProps) {
  return (
    <div className="flex justify-center rounded-lg bg-white p-4">
      <QRCodeSVG value={value} size={size} level="M" />
    </div>
  );
}
