const express =
require("express");

const admin =
require("firebase-admin");

const app =
express();

app.get("/",
(req, res) => {

res.send(
"KAP Rewards Running");
});

app.listen(
3000,
() => {

console.log(
"Server Started");
});