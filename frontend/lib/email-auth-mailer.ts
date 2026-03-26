import "server-only";

import nodemailer from "nodemailer";

function getEmailTransport() {
  if (!process.env.EMAIL_SERVER || !process.env.EMAIL_FROM) {
    throw new Error("Email transport is not configured");
  }
  return nodemailer.createTransport(process.env.EMAIL_SERVER);
}

export async function sendEmailLoginCode(input: { email: string; code: string }) {
  const transport = getEmailTransport();
  await transport.sendMail({
    from: process.env.EMAIL_FROM,
    to: input.email,
    subject: "The Council sign-in code",
    text: [
      "Use this code to sign in to The Council:",
      "",
      input.code,
      "",
      "This code expires in 15 minutes.",
    ].join("\n"),
  });
}
