import {
  addRecipient,
  removeRecipient,
  getRecipients
} from "../services/meetBot.js";

// GET /meet/:meetId/recipients
export const getRecipientsController = (req, res) => {
  try {
    const { meetId } = req.params;
    if (!meetId) {
      return res.status(400).json({ error: "meetId is required in params" });
    }

    const recipients = getRecipients(meetId);

    res.status(200).json({ meetId, recipients });
  } catch (error) {
    console.error("Error in getRecipientsController:", error);
    res.status(500).json({ error: "Failed to fetch recipients" });
  }
};

// POST /meet/:meetId/recipient
export const addRecipientController = (req, res) => {
  try {
    const { meetId } = req.params;
    const { email } = req.body;

    if (!meetId || !email) {
      console.log(req.params);
      console.log("meetId or email missing", meetId, email);
      return res.status(400).json({ error: "meetId and email are required" });
    }

    const updatedRecipients = addRecipient(meetId, email);

    res.status(201).json({
      message: "Recipient added successfully",
      meetId,
      recipients: updatedRecipients,
    });
  } catch (error) {
    console.error("Error in addRecipientController:", error);
    res.status(500).json({ error: "Failed to add recipient" });
  }
};

// DELETE /meet/:meetId/recipients
export const removeRecipientController = (req, res) => {
  try {
    const { meetId } = req.params;
    const { email } = req.body;

    if (!meetId || !email) {
      return res.status(400).json({ error: "meetId (param) and email (body) are required" });
    }

    const updatedRecipients = removeRecipient(meetId, email);
    
    res.status(200).json({
      message: "Recipient removed successfully",
      meetId,
      recipients: updatedRecipients,
    });
  } catch (error) {
    console.error("Error in removeRecipientController:", error);
    res.status(500).json({ error: "Failed to remove recipient" });
  }
};
