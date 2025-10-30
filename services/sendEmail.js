import { marked } from "marked";
import juice from "juice";
import { parseAudioContent } from "./utils/utils.js";

/**
 * Generates meeting minutes email HTML as a string (no React, no JSX)
 */
function MeetingMinutesEmail({
  meetingData,
  tasks,
  taskScreenUrl,
  momArtifactId,
  audioAnalysisDescription,
  audio_filename,
  preciseEmail = false,
}) {
  console.log("[EMAIL] taskScreenUrl:", taskScreenUrl, momArtifactId);

  const actionItemsUrl = taskScreenUrl
    ? `${taskScreenUrl}?activeAccordion=actionItems`
    : "";
  const meetingHighlightsUrl = taskScreenUrl
    ? `${taskScreenUrl}?activeAccordion=momItems`
    : "";

  const formattedDescription = parseAudioContent(audioAnalysisDescription);

  const hasMoreHighlights = !preciseEmail && meetingData?.length > 7;
  const hasMoreTakeaways =
    !preciseEmail && formattedDescription?.keyTakeaways?.length > 3;
  const hasMoreTasks = !preciseEmail && tasks?.length > 7;

  const displayedHighlights = preciseEmail
    ? meetingData
    : meetingData?.slice(0, 7);
  const displayedTasks = preciseEmail ? tasks : tasks?.slice(0, 7);

  console.log("formattedDescription", formattedDescription);
  const parsedDescription = marked.parse(formattedDescription.description);
  console.log("parsedDescription", parsedDescription);
  console.log("[EMAIL] taskScreenUrl new one:", taskScreenUrl);

  // === Build HTML using template literals ===
  const rawHtml = `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Meeting Highlights: ${audio_filename}</title>
  <style>
    body {font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif; line-height: 1.5; color: #333; background-color: #f9fafb; margin: 0; padding: 0;}
    .container {max-width: 1200px; width: 100%; background-color: #fff; border-radius: 12px; box-shadow: 0 5px 20px rgba(0,0,0,0.07); overflow: hidden; margin: 20px auto;}
    .header {background: #edf2f7; border-radius: 12px; padding: 10px; color: #151414; text-align: center;}
    .header h1 {font-size: 24px; font-weight: 600; margin: 0;}
    .header .powered {font-size: 12px; font-style: italic; margin: 4px 0 0;}
    .header .powered span {font-family: monospace; font-style: normal;}
    .header .meeting {font-weight: 500; font-size: 16px; margin-top: 8px;}
    .section-title {display: flex; align-items: center; background: linear-gradient(to right, #4776E6, #8E54E9); color: white; padding: 10px 15px; border-radius: 8px; margin: 15px 0 0;}
    .section-title svg {width: 18px; height: 18px; margin-right: 12px;}
    .section-title h2 {font-size: 16px; font-weight: 500; margin: 0;}
    .summary {background-color: #edf2f7; border-radius: 8px; padding: 15px; font-size: 15px; margin-top: 10px;}
    .highlight, .task {padding: 12px; margin-bottom: 12px; border-radius: 8px; background-color: #edf2f7;}
    .highlight {border-left: 4px solid #5a67d8;}
    .task {border-left: 4px solid #ed8936;}
    .highlight h3, .task h3 {display: flex; align-items: center; font-size: 16px; font-weight: 600; color: #2d3748; margin-bottom: 8px;}
    .highlight h3 span, .task h3 span {margin-right: 10px;}
    .highlight h3 span {color: #5a67d8;}
    .task h3 span {color: #ed8936;}
    .highlight p, .task p {margin: 0; padding-left: 34px; font-size: 15px; color: #4a5568;}
    .btn {display: inline-block; padding: 10px 20px; background: linear-gradient(to right, #4776E6, #8E54E9); color: white; text-decoration: none; border-radius: 6px; font-weight: 500;}
    .footer {padding: 20px; text-align: center; color: #a0aec0; font-size: 13px;}
    a {color: #5a67d8; text-decoration: none;}
  </style>
</head>
<body>
  <div class="container">

    <!-- Header -->
    <div class="header">
      <h1>Creative Workspace Meeting Highlights</h1>
      <p class="powered">powered by <span>techolution</span></p>
      <p class="meeting">Meeting: ${audio_filename.split(".").slice(0, -1).join(".")}</p>
    </div>

    <!-- Executive Summary -->
    <div class="section-title">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>
      </svg>
      <h2>Executive Summary</h2>
    </div>

    <div class="summary">
      ${parsedDescription}
      <h4>Key Takeaways</h4>
      ${preciseEmail
        ? formattedDescription.keyTakeaways
            ?.map((item) => `<div style="margin-left:16px;margin-bottom:12px">${item.id + 1}. ${item.content}</div>`)
            .join("") || ""
        : `
          ${formattedDescription.keyTakeaways
            ?.slice(0, 3)
            .map((item) => `<div style="margin-left:16px;margin-bottom:12px">${item.id + 1}. ${item.content}</div>`)
            .join("") || ""}
          ${hasMoreTakeaways
            ? `<div style="text-align:center;margin:20px 0"><a href="${taskScreenUrl}" class="btn">View More</a></div>`
            : ""
          }
        `}
    </div>

    <!-- Meeting Highlights -->
    <div class="section-title">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z"/>
      </svg>
      <h2>Meeting Highlights</h2>
    </div>

    <div id="initial-highlights">
      ${displayedHighlights
        ?.map((highlight, index) => {
          const linkForMom = taskScreenUrl || "";
          const audioLink = `${linkForMom}?activeAccordion=momItems&topicId=${highlight.minute_id}`;
          return `
            <div class="highlight">
              <h3>
                <span>${index + 1}</span>
                ${highlight.minute_title || `Highlight ${index + 1}`}
                <a target="_blank" href="${audioLink}" rel="noreferrer">Listen</a>
              </h3>
              <p>${highlight.minute_notes || ""}</p>
            </div>
          `;
        })
        .join("") || ""}

      ${hasMoreHighlights
        ? `<div style="text-align:center;margin:20px 0"><a href="${meetingHighlightsUrl}" class="btn">View More Highlights</a></div>`
        : ""}
    </div>

    <!-- Action Items -->
    <div class="section-title">
      <h2>Action Items</h2>
    </div>

    <div>
      ${displayedTasks && displayedTasks.length > 0
        ? displayedTasks
            .map((task, index) => `
              <div class="task">
                <h3>
                  <span>${index + 1}</span>
                  ${task.title || `Task ${index + 1}`}
                </h3>
                <p>${task.description || ""}</p>
              </div>
            `)
            .join("")
        : `<div class="task"><p>No tasks available.</p></div>`}

      ${hasMoreTasks
        ? `<div style="text-align:center;margin:20px 0"><a href="${actionItemsUrl}" class="btn">View More Action Items</a></div>`
        : ""}
    </div>

    <div class="footer">
      <p>This enhanced Meeting Highlights was generated for Creative WorkSpace</p>
      <p>© ${new Date().getFullYear()} Techolution</p>
    </div>
  </div>
</body>
</html>`;

  // Inline CSS for email clients
  return juice(rawHtml);
}

/**
 * Same function signature as before — now returns HTML string directly
 */
export async function generateMeetingMinutesEmailInMOMScreen(
  meetingData,
  tasks,
  momArtifactId,
  audioAnalysisDescription,
  audio_filename,
  selectedProjectId,
  backlogLink,
  preciseEmail = false
) {
  console.log(
    "[EMAIL] data received:",
    meetingData,
    audioAnalysisDescription,
    audio_filename,
    "preciseEmail:",
    preciseEmail
  );

  const emailLinkUrl = `${process.env.TASK_SCREEN_URL}/artifact/${momArtifactId}/mode/Meeting Mode`;

  console.log("[EMAIL] emailLinkUrl:", emailLinkUrl);

  const htmlString = MeetingMinutesEmail({
    meetingData,
    tasks,
    taskScreenUrl: emailLinkUrl,
    momArtifactId,
    audioAnalysisDescription,
    audio_filename,
    preciseEmail,
  });

  return htmlString;
}

export default generateMeetingMinutesEmailInMOMScreen;