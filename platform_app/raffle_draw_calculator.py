"""Calculo determinista de numeros ganadores externos."""

import json
import re


def calculate_winning_number(
    official_result,
    rule_type,
    rule_parameters,
    number_start,
    number_end,
):
    """
    Calcula el numero ganador conforme a la regla
    previamente configurada.

    Devuelve un entero dentro del intervalo del sorteo.
    No consulta ni modifica bases de datos.
    """

    result = str(official_result).strip()

    if not re.fullmatch(r"[0-9]{1,30}", result):
        raise ValueError(
            "El resultado oficial debe contener "
            "entre 1 y 30 cifras numericas."
        )

    if isinstance(rule_parameters, str):
        try:
            parameters = json.loads(rule_parameters)
        except (ValueError, TypeError):
            raise ValueError(
                "Parametros de adjudicacion invalidos."
            )
    else:
        parameters = rule_parameters

    if not isinstance(parameters, dict):
        raise ValueError(
            "Parametros de adjudicacion invalidos."
        )

    start = int(number_start)
    end = int(number_end)

    if start < 0 or end < start:
        raise ValueError(
            "Intervalo de numeracion invalido."
        )

    value = int(result)

    if rule_type == "last_digits":
        digits = parameters.get("digits")

        if type(digits) is not int or not 1 <= digits <= 12:
            raise ValueError(
                "Cantidad de ultimas cifras invalida."
            )

        if start != 0 or end != 10 ** digits - 1:
            raise ValueError(
                "La numeracion no corresponde "
                "a la regla de ultimas cifras."
            )

        if len(result) < digits:
            raise ValueError(
                "El resultado oficial tiene "
                "menos cifras de las necesarias."
            )

        winner = int(result[-digits:])

    elif rule_type == "modulo":
        divisor = parameters.get("divisor")

        if (
            type(divisor) is not int
            or divisor <= 0
            or start != 0
            or divisor != end - start + 1
        ):
            raise ValueError(
                "Divisor o intervalo del modulo invalido."
            )

        winner = value % divisor

    elif rule_type == "exact_number":
        minimum = parameters.get("minimum")
        maximum = parameters.get("maximum")

        if (
            type(minimum) is not int
            or type(maximum) is not int
            or minimum != start
            or maximum != end
        ):
            raise ValueError(
                "Intervalo del numero exacto invalido."
            )

        winner = value

    else:
        raise ValueError(
            "Metodo de adjudicacion desconocido."
        )

    if not start <= winner <= end:
        raise ValueError(
            "El numero resultante queda fuera "
            "del intervalo del sorteo."
        )

    return winner
