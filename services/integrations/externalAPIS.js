import axios from "axios";
import fs from "fs";
import FormData from 'form-data';
const uploadFile = async ({ projectID, files }) => {
    const uploadAPIURL = `${process.env.CW_BACKEND_URL}/gcs/upload-files/`;
  
    try {
      const formData = new FormData();
      formData.append("project_id", projectID);
      formData.append("isAI", "false");
  
      // ✅ Normalize files input to an array
      const fileList = Array.isArray(files) ? files : [files];
  
      // ✅ Append each file properly with filename and MIME type
      fileList.forEach((filePath) => {
        const fileStream = fs.createReadStream(filePath);
        formData.append("files", fileStream, {
          filename: filePath.split("/").pop(),
          contentType: "audio/wav", // Optional, helps backend validate
        });
      });
  
      const response = await axios.put(uploadAPIURL, formData, {
        headers: {
          ...formData.getHeaders(), // ✅ Important for boundary
          Accept: "application/json, text/plain, */*",
        },
        maxContentLength: Infinity,
        maxBodyLength: Infinity,
      });
  
      console.log("✅ File upload successful:", response.data);
      return response.data;
    } catch (error) {
      console.error("❌ Error uploading files:", error.response?.data || error.message);
      throw error;
    }
  };

const createProject = async ({ user, name, description, user_name }) => {
    const apiURL = `${process.env.CW_BACKEND_URL}/projects`;
  
    try {
      const response = await axios.post(
        apiURL,
        {
          user:[user],
          name,
          description,
          user_name,
        },
        {
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json, text/plain, */*",
            Origin: "https://dev.appmod.ai",
            Referer: "https://dev.appmod.ai/",
          },
        }
      );
  
      return response.data;
    } catch (error) {
      console.error("Error creating project:", error.response?.data || error.message);
      throw error;
    }
  };

  async function generateMeetingModeArtifact({projectId,userEmail,userName,modelType,LLM,audioName,displayName}) {
    const url = `${process.env.APPMOD_BACKEND_URL}/meeting_mode_artifact/gen_mm_artifact`;
  
    const payload = {
      audio_name: audioName,
      project_id: projectId,
      display_name: displayName,
      user_email: userEmail,
      user_name: userName,
      model_type: "google",
      large_language_model: "claude-3.5-sonnet"
    };
  
    try {
      const response = await axios.post(url, payload, {
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
      });
      if (response.status!==200) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
  
      const data = await response.data;
      return data;
  
    } catch (error) {
      console.error('Error calling API:', error);
      throw error;
    }
  }

const sendEmail = async ({
  to_email,
  subject,
  body,
  cc,
}) => {
  try {
    const response = await axios.post(
      `${process.env.APPMOD_BACKEND_URL}/utility/cw-email`,
      {
        to_email,
        subject,
        body,
        cc,
      },
      {
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
      }
    );

    console.log("Email sent successfully:", response.data);
    return response.data;
  } catch (error) {
    console.error("Error sending email:", error.response?.data || error.message);
    throw error;
  }
};


  
  // Example usage:
  // generateMeetingModeArtifact();
  export { uploadFile, createProject,generateMeetingModeArtifact,sendEmail };