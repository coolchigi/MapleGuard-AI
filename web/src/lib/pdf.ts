/**
 * Extract text from a reference-letter PDF, entirely in the browser.
 *
 * The letter carries personal data, so the file never leaves the device. We read it with pdf.js
 * client-side and only the extracted text goes to the API (the same text a user would have pasted),
 * where the server's Bedrock Guardrail then redacts PII before storage.
 *
 * pdf.js is imported dynamically so it never runs during SSR (it touches the DOM and a worker). The
 * worker is loaded from cdnjs at the exact installed version, which sidesteps bundler worker config.
 */
export async function extractPdfText(file: File): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc =
    `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

  const buffer = await file.arrayBuffer();
  const doc = await pdfjs.getDocument({ data: buffer }).promise;

  const pages: string[] = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const content = await page.getTextContent();
    const line = content.items
      .map((item) => ("str" in item ? item.str : ""))
      .join(" ");
    pages.push(line);
  }

  return pages
    .join("\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
