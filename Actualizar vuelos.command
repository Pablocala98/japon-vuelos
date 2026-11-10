#!/bin/bash
# Doble clic en este archivo para ver los vuelos más nuevos.
# - Si la app ya está publicada en GitHub: trae los resultados de GitHub y abre el dashboard (la búsqueda la hace GitHub).
# - Si todavía no: busca vuelos acá con el cupo que quede hoy y abre el dashboard actualizado.
cd "$(dirname "$0")" || exit 1

if git remote get-url origin >/dev/null 2>&1; then
  echo "Trayendo los últimos resultados desde GitHub..."
  echo
  if git pull --ff-only; then
    echo
    echo "Listo. Abriendo el dashboard..."
    open docs/index.html
  else
    echo
    echo "No se pudieron traer los resultados. Copiá lo que aparece arriba y pasáselo a Claude."
  fi
  echo
  echo "Para buscar vuelos nuevos ahora: botón \"Buscar vuelos nuevos\" de la página › \"Buscar ahora en GitHub\"."
  echo "Ya podés cerrar esta ventana."
  exit 0
fi

echo "Buscando vuelos a Japón... puede tardar unos minutos. No cierres esta ventana."
echo
if .venv/bin/python -m vuelos.buscar; then
  echo
  echo "Listo. Abriendo el dashboard..."
  open docs/index.html
else
  echo
  echo "La búsqueda terminó con un error. Copiá lo que aparece arriba y pasáselo a Claude."
fi
echo
echo "Ya podés cerrar esta ventana."
