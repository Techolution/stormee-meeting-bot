import express from "express";
import {
    addRecipientController,
    removeRecipientController,
    getRecipientsController
} from "../controllers/recipientController.js";

const router = express.Router({mergeParams: true});

router.get("/", getRecipientsController);
router.post("/", addRecipientController);
router.delete("/", removeRecipientController);

export default router;