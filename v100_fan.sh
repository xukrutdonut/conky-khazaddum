#!/usr/bin/env bash
# Historial del duty del ventilador de la Tesla V100 (%) para execgraph.
# Va de 0..100 directamente: conky la acepta sin normalizar.
exec /home/arkantu/.config/conky/get_v100_fan_val.sh DUTY
