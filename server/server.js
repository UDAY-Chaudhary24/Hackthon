const express = require("express");
const app = express();

// Parse JSON data
app.use(express.json());

// Serve frontend files
app.use(express.static("client"));

// Test API route
app.get("/api/message", (req, res) => {
  res.json({ message: "Hello from the backend" });
});

// Start the server
app.listen(3000, () => {
  console.log("Server running at http://localhost:3000");
});
