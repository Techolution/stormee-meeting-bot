import {
  addRecipient,
  removeRecipient,
  getRecipients
} from "../services/meetBot.js";

// GET /recipient
export const getRecipientsController = (req, res) => {
  try {
    const recipients = getRecipients(); // Fetch all recipients of the current meeting

    res.status(200).json({ recipients });
  } catch (error) {
    console.error("Error in getRecipientsController:", error);
    res.status(500).json({ error: "Failed to fetch recipients" });
  }
};

// POST /recipient
export const addRecipientController = (req, res) => {
  try {
    const { email } = req.body;

    if (!email) {
      console.log("email missing", meetId, email);
      return res.status(400).json({ error: "meetId and email are required" });
    }

    const updatedRecipients = addRecipient(email);

    res.status(201).json({
      message: "Recipient added successfully",
      recipients: updatedRecipients,
    });
  } catch (error) {
    console.error("Error in addRecipientController:", error);
    res.status(500).json({ error: "Failed to add recipient" });
  }
};

// DELETE /recipient
export const removeRecipientController = (req, res) => {
  try {
    const { email } = req.body;

    if (!email) {
      return res.status(400).json({ error: "email (body) is required" });
    }

    const updatedRecipients = removeRecipient(email);

    res.status(200).json({
      recipients: updatedRecipients,
    });
  } catch (error) {
    console.error("Error in removeRecipientController:", error);
    res.status(500).json({ error: "Failed to remove recipient" });
  }
};
