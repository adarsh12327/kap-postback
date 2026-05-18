const express =
require("express");

const admin =
require("firebase-admin");

const app =
express();

const firebaseKey =
JSON.parse(
process.env
.FIREBASE_KEY);

admin.initializeApp({
credential:
admin.credential
.cert(firebaseKey),

databaseURL:
"https://kap-rewards-afb54-default-rtdb.firebaseio.com"
});

const db =
admin.database();

app.get("/",
(req, res) => {

res.send(
"KAP Rewards Running");
});

app.get(
"/postback",
async (
req,
res) => {

try {

const uid =
req.query.uid;

const reward =
parseInt(
req.query.reward
|| 0);

if(!uid ||
!reward) {

return res.send(
"Missing uid or reward");
}

const userRef =
db.ref(
`users/${uid}/coins`);

const snap =
await userRef.once(
"value");

const oldCoins =
parseInt(
snap.val()
|| 0);

await userRef.set(
oldCoins
+ reward);

res.send(
"Reward Added");

} catch(e) {

res.send(
e.toString());
}
});

app.listen(
3000,
() => {

console.log(
"Server Started");
});
