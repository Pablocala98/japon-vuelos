# ✈️ Vuelos a Japón

App personal y gratuita que busca todos los días vuelos baratos de **Buenos Aires a Japón** (Tokio u Osaka) para 2 personas, con salidas en **todo 2027** (abril a junio se revisan más seguido) y unos **20 días en Japón**. Guarda el historial de precios y muestra todo en una página web.

**Página:** https://pablocala98.github.io/japon-vuelos/

## Qué hace

- **Todos los días a las 8:00 (hora de Buenos Aires)**, GitHub busca vuelos solo, sin que tengas la compu prendida.
- Busca **desde Buenos Aires** (EZE/AEP) y **desde San Pablo** (GRU, sumando un pasaje aparte Buenos Aires–San Pablo), a **Tokio** (NRT/HND) y **Osaka** (KIX/ITM), también entrando por una ciudad y saliendo por la otra.
- **Stopovers** en Madrid (Iberia) o Estambul (Turkish): elegís cuántos días, si a la ida o a la vuelta y el mes, y la app busca el pasaje.
- Le pone a cada opción una categoría según el precio **para los 2, con valijas**:
  - 🟢 **ideal**: hasta USD 3.500
  - ✅ **comprar**: hasta USD 3.800
  - 👀 **casi**: hasta USD 4.000
  - 🔴 **todavía caro**: más de USD 4.000
- Compara con los días anteriores y avisa si bajó o subió.
- Junta las **promociones** de promociones-aereas.com.ar que sirven para Japón, Asia o tus tarjetas Galicia (sin Éminent).

## La página

Arriba, 3 números: lo más barato, tu tope y cuánto falta. Debajo, pestañas:

- **✈️ Vuelos**: cada vuelo es una tarjeta, como en un buscador de pasajes. Muestra horarios, escalas (bandera, aeropuerto y horas de espera), duración de la ida y la vuelta, equipaje (🎒 🧳), días en Japón y el botón **Comprar**. Se puede filtrar por origen (🇦🇷/🇧🇷), destino, escalas, valija incluida y mes, y ordenar por precio, escalas, duración o fecha. También se pueden **comparar** hasta 3.
- **🏨 Stopovers**: elegís ciudad, días, ida o vuelta y mes. Ves cuándo estás en cada lugar y pedís la búsqueda.
- **📅 Fechas**: calendario de precios, fechas más baratas y "Armá tu viaje".
- **📈 Precio**: cómo se movió el mejor precio.
- **🏷️ Promos y más**: promociones, estado de la app y cómo se calculan los precios.

> Los precios son **para los 2**. "Sin valijas" es lo que muestra la aerolínea al principio. "Con valijas" suma una **estimación** de USD 80 por valija y por tramo cuando no está confirmado que estén incluidas.

## Buscar vuelos ahora

1. En la página, tocá **🔄 Buscar vuelos nuevos** › **Buscar ahora en GitHub**.
2. En GitHub, tocá **Run workflow** y después el botón verde **Run workflow**.
3. Esperá unos 5 minutos y recargá la página.

También funciona desde el celular, con la sesión de GitHub abierta.

Si ya se buscó ese día, una nueva búsqueda solo completa lo que haya faltado: el cupo gratis es por día.

## Pedir un stopover

1. En la pestaña **🏨 Stopovers** elegí ciudad, días, ida o vuelta y mes. La página te muestra los valores.
2. Tocá **Abrir GitHub** › **Run workflow** y elegí esos mismos valores.
3. Botón verde **Run workflow**. En unos 5 minutos recargá la página.

Cada pedido prueba las 2 salidas más baratas de ese mes y gasta 6 consultas: alcanzan unos **10 pedidos por mes**. Los resultados se muestran 14 días.

## Cambiar las preferencias

Todo está en **`config.yaml`**: fechas, días en Japón, escalas, precios tope, valijas, etc. Para cambiarlo desde la web:

1. En GitHub, abrí `config.yaml` y tocá el lápiz ✏️.
2. Cambiá el valor y tocá **Commit changes**.
3. La próxima búsqueda ya usa lo nuevo.

## Es gratis: los límites

| Fuente | Cupo gratis | Uso de la app |
|---|---|---|
| **Ignav** | 1.000 consultas, **por única vez** | hasta 9 por día (unos 3 meses y medio) |
| **SerpApi** (Google Flights) | 250 por mes | hasta 6 por día, más hasta 60 por mes para stopovers |
| **GitHub** (Actions y Pages) | gratis para repositorios públicos | una búsqueda por día |

El contador está en `data/consultas.json`. La app nunca se pasa de esos límites: cuando se termina el cupo, deja de consultar esa fuente y sigue con la otra.

## Las claves

Las claves de Ignav y SerpApi **nunca** se suben al repositorio:

- **En GitHub** están guardadas como secretos: Settings › Secrets and variables › Actions (`IGNAV_API_KEY` y `SERPAPI_API_KEY`).
- **En tu Mac** están en el archivo `.env`, que git ignora. `.env.example` muestra el formato.

## Usarla en tu Mac (opcional)

Doble clic en **`Actualizar vuelos.command`**: trae los últimos resultados de GitHub y abre la página.

Para programar o hacer pruebas:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -b tests   # pruebas, sin internet
.venv/bin/python -m vuelos.buscar --solo-plan    # muestra qué buscaría hoy, sin gastar consultas
```

> No busques desde la Mac y desde GitHub el mismo día: cada una tiene su propio contador y podrían pasarse del cupo.

## Cómo está armada

```
config.yaml              tus preferencias
vuelos/                  el programa (Python)
  buscar.py              la búsqueda del día
  fuentes/               Ignav y SerpApi
  planificador.py        qué fechas buscar cada día (rota para cubrir toda la ventana)
  evaluar.py             reglas del viaje, valijas y categorías
  analisis.py            historial y comparación con días anteriores
  promociones.py         promociones aéreas
  publicar.py            arma los datos de la página
docs/                    la página (index.html + datos.js)
data/                    resultados de cada día, historial y contador de consultas
tests/                   pruebas automáticas
.github/workflows/       la búsqueda diaria en GitHub
```

Datos de aeropuertos: [OurAirports](https://ourairports.com/data/) (dominio público).
