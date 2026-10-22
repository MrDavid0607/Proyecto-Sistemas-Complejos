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


EXECUTORS = {
    "regresion_lineal": linear_regression,
    "linear_regression": linear_regression,
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
