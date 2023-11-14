import sqlite3
import ast
import json
from contextlib import closing
from ctat.cell_type_annotation import (CellTypeAnnotation, Annotation, Labelset, AnnotationTransfer,
                                       UserAnnotation, AutomatedAnnotation, serialize_to_json)

CONFLICT_TBL_EXT = "_conflict"

cas_table_postfixes = ["_annotation", "_labelset", "_metadata", "_annotation_transfer"]


def export_cas_data(sqlite_db: str, output_file: str):
    """
    Reads all data from TDT tables and generates CAS json.
    :param sqlite_db: db file path
    :param output_file: output json path
    """
    cta = CellTypeAnnotation("", list())

    cas_tables = get_table_names(sqlite_db)
    for table_name in cas_tables:
        if table_name.endswith("_metadata"):
            parse_metadata_data(cta, sqlite_db, table_name)
        elif table_name.endswith("_annotation"):
            parse_annotation_data(cta, sqlite_db, table_name)
        elif table_name.endswith("_labelset"):
            parse_labelset_data(cta, sqlite_db, table_name)
        elif table_name.endswith("_annotation_transfer"):
            parse__annotation_transfer_data(cta, sqlite_db, table_name)

    serialize_to_json(cta, output_file, True)
    print("CAS json successfully created at: {}".format(output_file))
    return cta


def parse_metadata_data(cta, sqlite_db, table_name):
    """
    Reads 'Metadata' table data into the CAS object
    :param cta: cell type annotation schema object.
    :param sqlite_db: db file path
    :param table_name: name of the metadata table
    :return : True if metadata can be ingested, False otherwise
    """
    with closing(sqlite3.connect(sqlite_db)) as connection:
        with closing(connection.cursor()) as cursor:
            rows = cursor.execute("SELECT * FROM {}_view".format(table_name)).fetchall()
            columns = list(map(lambda x: x[0], cursor.description))
            if len(rows) > 0:
                auto_fill_object_from_row(cta, columns, rows[0])
                return True
    return False


def parse_annotation_data(cta, sqlite_db, table_name):
    """
    Reads 'Annotation' table data into the CAS object
    :param cta: cell type annotation schema object.
    :param sqlite_db: db file path
    :param table_name: name of the metadata table
    """
    with closing(sqlite3.connect(sqlite_db)) as connection:
        with closing(connection.cursor()) as cursor:
            rows = cursor.execute("SELECT * FROM {}_view".format(table_name)).fetchall()
            columns = list(map(lambda x: x[0], cursor.description))
            if len(rows) > 0:
                if not cta.annotations:
                    annotations = list()
                else:
                    annotations = cta.annotations
                for row in rows:
                    annotation = Annotation("", "")
                    auto_fill_object_from_row(annotation, columns, row)
                    # handle user_annotations
                    user_annotations = list()
                    obj_fields = vars(annotation)
                    for column in columns:
                        if column not in obj_fields and column not in ["row_number", "message"]:
                            user_annotations.append(UserAnnotation(column, str(row[columns.index(column)])))
                    annotation.user_annotations = user_annotations

                    annotations.append(annotation)
                cta.annotations = annotations


def parse_labelset_data(cta, sqlite_db, table_name):
    """
    Reads 'Labelset' table data into the CAS object
    :param cta: cell type annotation schema object.
    :param sqlite_db: db file path
    :param table_name: name of the metadata table
    """
    with closing(sqlite3.connect(sqlite_db)) as connection:
        with closing(connection.cursor()) as cursor:
            rows = cursor.execute("SELECT * FROM {}_view".format(table_name)).fetchall()
            columns = list(map(lambda x: x[0], cursor.description))
            if len(rows) > 0:
                if not cta.labelsets:
                    labelsets = list()
                else:
                    labelsets = cta.labelsets
                renamed_columns = [str(c).replace("automated_annotation_", "") for c in columns]
                for row in rows:
                    labelset = Labelset("", "")
                    auto_fill_object_from_row(labelset, columns, row)
                    # handle automated_annotation
                    if row[renamed_columns.index("algorithm_name")]:
                        automated_annotation = AutomatedAnnotation("", "", "", "")
                        auto_fill_object_from_row(automated_annotation, renamed_columns, row)
                        labelset.automated_annotation = automated_annotation
                    labelsets.append(labelset)
                cta.labelsets = labelsets


def parse__annotation_transfer_data(cta, sqlite_db, table_name):
    """
    Reads 'Annotation Transfer' table data into the CAS object
    :param cta: cell type annotation schema object.
    :param sqlite_db: db file path
    :param table_name: name of the metadata table
    """
    with closing(sqlite3.connect(sqlite_db)) as connection:
        with closing(connection.cursor()) as cursor:
            rows = cursor.execute("SELECT * FROM {}_view".format(table_name)).fetchall()
            columns = list(map(lambda x: x[0], cursor.description))
            if len(rows) > 0:
                for row in rows:
                    if "target_node_accession" in columns and row[columns.index("target_node_accession")]:
                        filtered_annotations = [a for a in cta.annotations
                                                if a.cell_set_accession == row[columns.index("target_node_accession")]]
                        if filtered_annotations:
                            at = AnnotationTransfer("", "", "", "", "")
                            auto_fill_object_from_row(at, columns, row)
                            if filtered_annotations[0].transferred_annotations:
                                filtered_annotations[0].transferred_annotations.append(at)
                            else:
                                filtered_annotations[0].transferred_annotations = [at]


def get_table_names(sqlite_db):
    """
    Queries 'table' table to get all CAS related table names
    :param sqlite_db: db file path
    :return: list of CAS related table names
    """
    cas_tables = list()
    with closing(sqlite3.connect(sqlite_db)) as connection:
        with closing(connection.cursor()) as cursor:
            rows = cursor.execute("SELECT * FROM table_view").fetchall()
            columns = list(map(lambda x: x[0], cursor.description))
            table_column_index = columns.index('table')
            for row in rows:
                if str(row[table_column_index]).endswith(tuple(cas_table_postfixes)):
                    cas_tables.append(str(row[table_column_index]))
    return cas_tables


def auto_fill_object_from_row(obj, columns, row):
    """
    Automatically sets attribute values of the obj from the given db table row.
    :param obj: object to fill
    :param columns: list of the db table columns
    :param row: db record
    """
    for column in columns:
        if hasattr(obj, column):
            value = row[columns.index(column)]
            if value:
                if value.startswith("[") and value.endswith("]"):
                    value = ast.literal_eval(value)
                setattr(obj, column, value)
        if 'message' in columns and row[columns.index('message')]:
            # process invalid data
            messages = json.loads(row[columns.index('message')])
            for msg in messages:
                if msg["column"] in columns:
                    setattr(obj, msg["column"], msg["value"])

