# Sección de la Fase 3 para el informe (LaTeX)

Es la **sección 12** del informe del proyecto (las secciones 1–10 son la Fase 1 y la 11 la Fase 2).

| Archivo | Qué es |
|---|---|
| `seccion_fase3.tex` | Texto de la sección (objetivo, despliegue en 3 PCs, API, aplicaciones, estrategias, metodología, pruebas, limitaciones, conclusión) |
| `fase3_resultados.tex` | Tablas y figuras de los experimentos. **Se genera solo** (ver abajo); no editar a mano |
| `figuras/` | Gráficas PNG de los experimentos (también generadas) |
| `fase3_independiente.tex` | Documento mínimo para compilar la sección sola |

## Añadirla al documento principal (Overleaf)

1. Sube a Overleaf, junto a tu `main.tex`, los archivos `seccion_fase3.tex` y `fase3_resultados.tex`
   y la carpeta `figuras/` (si ya tienes una carpeta `figuras`, copia dentro los PNG).
2. En `main.tex`, justo antes de `\end{document}`, escribe:

   ```latex
   \input{seccion_fase3}
   ```

3. Compila. Solo se necesita el paquete `graphicx`, que el documento ya usa para sus figuras.

Para ver la sección sola, compila `fase3_independiente.tex`.

## Actualizar los números con los 3 PCs reales

```powershell
python experiments\run_experiments.py --id nodo-01 --http-port 0     # genera experiments/results/<fecha>/
python experiments\report.py                                         # actualiza el informe .md y este .tex
```

`report.py` reescribe `fase3_resultados.tex` y las figuras con la corrida más reciente. Después solo hay que
volver a subir esos archivos a Overleaf. Si la corrida es de un solo PC, el texto lo indica; si es de
tres PCs, lo dice sin que haya que cambiar nada.
