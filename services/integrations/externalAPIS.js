import axios from "axios";
import fs from "fs";
import path from "path";
import FormData from 'form-data';
const uploadFile = async ({ projectID, files }) => {
    const uploadAPIURL = "https://dev-creative-workspace.techo.camp/backend/gcs/upload-files/";
  
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
    const apiURL = "https://dev-creative-workspace.techo.camp/backend/projects";
  
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
  export { uploadFile, createProject };