function tickDateTime(){
  var el = document.getElementById('datetime');
  if(!el) return;
  var now = new Date();
  el.textContent = now.toLocaleDateString('ru-RU') + ' ' + now.toLocaleTimeString('ru-RU');
}
setInterval(tickDateTime, 1000);
tickDateTime();
