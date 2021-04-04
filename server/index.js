const express = require('express')
const app = express()
app.get('/', (req, res) => {
  res.send('Aaron Hall, King of Mongolia/Brooklyn')
})
app.listen(3000, () => console.log('Server running on port 3000'))
