# MCP Crafting Planner 🛠️🎮

Permite consultar recetas y calcular materiales de fabricación de un videojuego desde un cliente MCP local. Agrupa las necesidades de ingredientes compartidos antes de redondear los lotes, descuenta el inventario disponible y muestra sobrantes y pasos de fabricación.

Creado el **3 de noviembre de 2026**. Código, recetas y datos originales bajo licencia MIT. **Python 3.10+**, biblioteca estándar únicamente; sin paquetes externos, modelos, claves ni servicios.

## Probar sin una aplicación de IA

```bash
git clone https://github.com/alvaroalcalaa/mcp-crafting-planner.git
cd mcp-crafting-planner
python demo_client.py
python -m unittest -v
```

`demo_client.py` lanza el servidor en un subproceso y envía mensajes reales por stdin/stdout: `initialize`, `notifications/initialized`, `tools/list` y `tools/call`. Valida la respuesta y muestra el plan. Es un cliente de prueba propio, no un SDK oficial ni un modelo de IA.

La demo pide **3 linternas**, con **1 placa y 1 unidad de mineral** ya disponibles:

| Resultado | Cantidad |
|---|---:|
| Mineral adicional (`ore`) | 3 |
| Fragmentos adicionales (`shard`) | 6 |
| Cristales sobrantes | 1 |
| Placas sobrantes | 1 |

El resultado supone adquirir los materiales base faltantes antes de seguir los pasos. No indica que el inventario actual baste por sí solo. Las tres linternas solicitadas se consideran entregadas al objetivo; no aparecen entre los sobrantes.

También se puede usar únicamente la CLI, que imprime JSON sin modificar archivos:

```bash
python planner.py examples/recipes.json lantern --quantity 3 --inventory examples/inventory.json
```

## Usar el servidor MCP

El proceso de servidor se inicia con:

```bash
python server.py examples/recipes.json
```

Ese comando espera mensajes JSON-RPC por stdin y solo escribe mensajes MCP por stdout. No es una interfaz interactiva de terminal. Termina al cerrar stdin. Los errores de catálogo se escriben en stderr.

En un cliente compatible configura un servidor **stdio**, con el ejecutable de Python como comando y dos argumentos absolutos: la ruta a `server.py` y la ruta a tu catálogo. Por ejemplo, en clientes que utilicen la convención `mcpServers`:

```json
{
  "mcpServers": {
    "crafting": {
      "command": "python",
      "args": ["/ruta/absoluta/mcp-crafting-planner/server.py", "/ruta/absoluta/mcp-crafting-planner/examples/recipes.json"]
    }
  }
}
```

Ajusta comando y rutas a tu sistema. Ese formato de configuración depende del cliente; no forma parte del protocolo y **no se ha probado con una aplicación de IA concreta**.

### Versión y alcance del protocolo

Implementación pequeña, escrita sin SDK, orientada explícitamente a **MCP 2025-11-25**. Usa inicialización de sesión y JSON-RPC delimitado por saltos de línea UTF-8. Si el cliente propone otra versión, el servidor responde con 2025-11-25; el cliente debe poder aceptar esa versión o desconectarse. **No implementa MCP 2026-07-28 ni su flujo sin handshake.** No se anuncia compatibilidad con todas las funciones MCP.

Implementa `initialize`, `notifications/initialized`, `ping`, `tools/list` y `tools/call`. No ofrece HTTP, recursos, prompts, muestreo, paginación, suscripciones, tareas en segundo plano ni llamadas a otros servidores. Las notificaciones sin operación aplicable se ignoran. Atiende cada petición de forma síncrona. La sesión se cierra si una línea supera 256 KiB.

Las dos herramientas se anuncian como de solo lectura e idempotentes; cada llamada recalcula un plan independiente, sin memoria de inventario ni cambios persistentes.

| Herramienta | Argumentos | Resultado |
|---|---|---|
| `list_recipes` | Objeto vacío | Recetas cargadas y lista de materiales base |
| `plan_craft` | `target`, opcionales `quantity` e `inventory` | Materiales adicionales, pasos, inventario usado y sobrantes |

Ejemplo de argumentos de `plan_craft`:

```json
{"target": "lantern", "quantity": 3, "inventory": {"plate": 1, "ore": 1}}
```

La herramienta devuelve el mismo objeto como `structuredContent` y como texto JSON en `content`. Los errores de cálculo o validación de argumentos se devuelven con `isError: true`. Métodos o herramientas desconocidos generan errores JSON-RPC. No se envían órdenes de juego ni se ejecutan comandos proporcionados por el cliente.

## Definir recetas

```json
{
  "recipes": {
    "plate": {"yield": 3, "inputs": {"ore": 2}},
    "lantern": {"yield": 1, "inputs": {"plate": 2}}
  }
}
```

`yield` es la cantidad producida por lote; `inputs`, las cantidades consumidas por lote. Cada producto tiene una única receta. Todo ingrediente que no sea producto de una receta es un material base. Los IDs distinguen mayúsculas y admiten letras ASCII, números, guion y guion bajo, con hasta 64 caracteres. Se rechazan ciclos, recetas vacías, cantidades no enteras y claves JSON repetidas.

El inventario es un objeto de cantidades por ID; todos los IDs deben existir entre los productos o ingredientes del catálogo. Cantidades e inventario: enteros hasta 1000000000; el objetivo y las cantidades de receta deben ser positivos, el stock puede ser cero. Los booleanos se rechazan. Si cualquier demanda, producción o consumo intermedio supera ese límite, el cálculo falla con un mensaje de cantidad fuera de rango.

Límites adicionales: archivo de hasta 1 MiB, entre 1 y 50 recetas, hasta 10 ingredientes por receta y 100 objetos distintos. Se carga una copia del catálogo al iniciar; reinicia el proceso para aplicar cambios. Las llamadas no aceptan rutas de archivos.

## Cómo se calcula

Se construye un orden topológico del grafo. La demanda se propaga del objetivo hacia los ingredientes, sumando todas las demandas que llegan al mismo objeto antes de procesarlo. Primero se descuenta su stock; si falta cantidad, se redondean los lotes hacia arriba y se propaga su consumo. La producción sobrante queda en `remaining_inventory`.

`craft_steps` se devuelve con ingredientes fabricados antes que sus productos, para poder reproducir el plan tras añadir `base_needed` al inventario inicial. `inventory_used` recoge solo unidades consumidas del stock suministrado. El orden es determinista; no hay recetas alternativas ni búsqueda de un coste óptimo entre opciones.

## Límites reales y comprobaciones

No modela estaciones de trabajo, tiempos, herramientas reutilizables, durabilidad, probabilidades, subproductos, monedas, calidad ni disponibilidad comercial. Todo ingrediente se consume y cada lote produce una cantidad fija. Es una calculadora de diseño para un catálogo pequeño, no una integración con el inventario de un juego.

Las pruebas verifican redondeo, inventario, ingredientes compartidos, conservación de recursos reproduciendo los pasos, determinismo, ciclos, límites y CLI. También lanzan un servidor real por stdio, envían un mensaje mal formado seguido de una sesión válida y comprueban respuestas y cierre por EOF. **Esto prueba el intercambio con el cliente local incluido, no la interoperabilidad con un SDK oficial o una aplicación externa.**

Referencias oficiales consultadas para la revisión implementada: [ciclo de vida](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/lifecycle.mdx), [transporte](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/transports.mdx) y [herramientas](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx).

## Dependencias y licencia

Solo módulos estándar de Python. No se envían datos por red. CLI y servidor terminan con 2 ante errores locales; las peticiones MCP fallidas se comunican por el protocolo sin cerrar la sesión, salvo una línea excesiva. Licencia MIT en `LICENSE`.
