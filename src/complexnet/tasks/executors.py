"""Ejecutores de tareas disponibles en cada nodo.

Cada tarea del tipo `task_name` se resuelve con una función registrada aquí.
La tarea de IA de la fase 2 es una regresión lineal (mínimos cuadrados) sobre
datos sintéticos generados con una semilla, de modo que cualquier nodo puede
reproducir su porción del dataset sin transferirlo por la red.
"""

import time

import numpy as np


def linear_regression(parameters):
    """Ajusta y = a*x + b sobre datos sintéticos y devuelve el modelo y su error.

    parameters: n_samples, seed, true_slope, true_intercept, noise,
    learning_rate/epochs (opcional: descenso de gradiente en vez de forma cerrada).
    """
    n_samples = int(parameters.get("n_samples", 1000))
    seed = int(parameters.get("seed", 0))
    true_slope = float(parameters.get("true_slope", 2.35))
    true_intercept = float(parameters.get("true_intercept", 0.81))
    noise = float(parameters.get("noise", 0.5))

    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, 10.0, n_samples)
    y = true_slope * x + true_intercept + rng.normal(0.0, noise, n_samples)

    if "epochs" in parameters:
        learning_rate = float(parameters.get("learning_rate", 0.01))
        slope, intercept = 0.0, 0.0
        for _ in range(int(parameters["epochs"])):
            error = slope * x + intercept - y
            slope -= learning_rate * 2.0 * float(np.mean(error * x))
            intercept -= learning_rate * 2.0 * float(np.mean(error))
        method = "gradient_descent"
    else:
        design = np.vstack([x, np.ones_like(x)]).T
        (slope, intercept), *_ = np.linalg.lstsq(design, y, rcond=None)
        method = "least_squares"

    predictions = slope * x + intercept
    mse = float(np.mean((y - predictions) ** 2))
    variance = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - float(np.sum((y - predictions) ** 2)) / variance if variance else 0.0
    return {
        "slope": round(float(slope), 4),
        "intercept": round(float(intercept), 4),
        "mse": round(mse, 4),
        "r2": round(r2, 4),
        "n_samples": n_samples,
        "method": method,
    }


def echo(parameters):
    return {"echo": parameters}


# ---------------------------------------------------------------------------
# Aplicación de IA: regresión lineal multivariable distribuida por fragmentos
# ---------------------------------------------------------------------------

def _model_weights(n_features, model_seed):
    """Pesos verdaderos [w1..wd, b] compartidos por todos los fragmentos."""
    rng = np.random.default_rng(model_seed)
    return rng.uniform(-3.0, 3.0, n_features + 1)


def _shard_data(parameters):
    n_samples = int(parameters.get("n_samples", 5000))
    n_features = int(parameters.get("n_features", 3))
    noise = float(parameters.get("noise", 0.5))
    weights = _model_weights(n_features, int(parameters.get("model_seed", 1234)))
    shard = int(parameters.get("shard", 0))
    rng = np.random.default_rng(int(parameters.get("data_seed", 99)) + shard)
    x = rng.normal(0.0, 2.0, (n_samples, n_features))
    y = x @ weights[:-1] + weights[-1] + rng.normal(0.0, noise, n_samples)
    return x, y, weights


def normal_equations(parameters):
    """Estadísticos suficientes de un fragmento: XtX, Xty, n, Σy, Σy².

    La regresión por mínimos cuadrados se puede resolver exactamente sumando
    estos estadísticos de todos los fragmentos (cada nodo trabaja sobre su
    porción de los datos y solo viaja una matriz pequeña por la red).
    """
    x, y, _ = _shard_data(parameters)
    design = np.hstack([x, np.ones((x.shape[0], 1))])
    return {
        "xtx": (design.T @ design).tolist(),
        "xty": (design.T @ y).tolist(),
        "n": int(x.shape[0]),
        "sum_y": float(y.sum()),
        "sum_yy": float((y * y).sum()),
    }


def evaluate_model(parameters):
    """Evalúa pesos [w1..wd, b] sobre un fragmento de datos nuevo."""
    x, y, _ = _shard_data(parameters)
    w = np.asarray(parameters["weights"], dtype=float)
    predictions = x @ w[:-1] + w[-1]
    sse = float(np.sum((y - predictions) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    return {
        "n": int(len(y)),
        "sse": sse,
        "sst": sst,
        "mse": sse / len(y),
        "r2": 1.0 - sse / sst if sst else 0.0,
    }


# ---------------------------------------------------------------------------
# Aplicación de procesamiento: cálculo colaborativo y análisis de texto
# ---------------------------------------------------------------------------

def monte_carlo_pi(parameters):
    """Cuenta puntos dentro del círculo unidad (estimación de pi)."""
    n_points = int(parameters.get("n_points", 2_000_000))
    rng = np.random.default_rng(int(parameters.get("seed", 0)))
    inside = 0
    remaining = n_points
    while remaining > 0:
        batch = min(remaining, 1_000_000)
        x = rng.random(batch)
        y = rng.random(batch)
        inside += int(np.count_nonzero(x * x + y * y <= 1.0))
        remaining -= batch
    return {"inside": inside, "total": n_points}


def word_count(parameters):
    """Frecuencia de palabras (≥ 4 letras) de un fragmento de texto."""
    import re
    from collections import Counter

    text = str(parameters.get("text", "")).lower()
    words = re.findall(r"[a-záéíóúñü]{4,}", text)
    counts = Counter(words)
    top = int(parameters.get("top", 400))
    return {"counts": dict(counts.most_common(top)), "words": len(words)}


EXECUTORS = {
    "regresion_lineal": linear_regression,
    "linear_regression": linear_regression,
    "normal_equations": normal_equations,
    "evaluate_model": evaluate_model,
    "monte_carlo_pi": monte_carlo_pi,
    "word_count": word_count,
    "echo": echo,
}


def execute(task_name, parameters):
    """Ejecuta la tarea. `simulate_seconds` emula entrenamientos más largos."""
    function = EXECUTORS.get(task_name)
    if function is None:
        raise ValueError(f"tarea desconocida: {task_name!r}")
    parameters = dict(parameters or {})
    simulate = float(parameters.pop("simulate_seconds", 0.0))
    result = function(parameters)
    if simulate > 0:
        time.sleep(simulate)
    return result
