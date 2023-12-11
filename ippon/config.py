# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import configparser
import os
import os.path


class StaticConfiguration(object):
    _config_relative_directory_path = ".config/ippon/"
    _config_data_directory_name = "data"
    _config_data_raw_directory_name = "raw"
    _config_data_json_directory_name = "json"
    _config_competitions_directory_name = "competitions"
    _config_logos_directory_name = "logos"
    _config_relative_filename = "config.ini"

    # Prepend the configuration directory path with the user home directory
    config_directory_path = os.path.join(os.path.expanduser("~"),
                                         _config_relative_directory_path)
    config_file_path = os.path.join(config_directory_path,
                                    _config_relative_filename)
    config_data_directory_path = os.path.join(config_directory_path,
                                              _config_data_directory_name)
    config_data_raw_directory_path = os.path.join(config_data_directory_path,
                                                  _config_data_raw_directory_name)  # noqa: E501
    config_data_json_directory_path = os.path.join(config_data_directory_path,
                                                   _config_data_json_directory_name)  # noqa: E501
    config_competitions_directory_path = os.path.join(config_directory_path,
                                                      _config_competitions_directory_name)  # noqa: E501
    config_logos_directory_path = os.path.join(config_directory_path,
                                               _config_logos_directory_name)  # noqa: E501


def generate_directory_structure():
    """
    Generate the directory structure
    """

    for directory in [StaticConfiguration.config_directory_path,
                      StaticConfiguration.config_data_directory_path,
                      StaticConfiguration.config_data_raw_directory_path,
                      StaticConfiguration.config_data_json_directory_path,
                      StaticConfiguration.config_competitions_directory_path,
                      StaticConfiguration.config_logos_directory_path]:
        if not os.path.exists(directory):
            os.makedirs(directory)


def generate_directory_competitions_structure(competition):
    """
    Generate the directory structure for competitions
    """
    name = competition["name"]
    date_start = competition["start"]
    date_end = competition["end"]
    year_start = date_start.split("/")[2]
    year_end = date_end.split("/")[2]

    for year in set([year_start, year_end]):
        # Create year directory
        year_directory_path = os.path.join(StaticConfiguration.config_competitions_directory_path, year)  # noqa: E501
        if not os.path.exists(year_directory_path):
            os.makedirs(year_directory_path)

        # Create competition directory
        competition_directory_path = os.path.join(year_directory_path, name)
        if not os.path.exists(competition_directory_path):
            os.makedirs(competition_directory_path)

        # Create data directories
        for directory in [StaticConfiguration.config_data_raw_directory_path,
                          StaticConfiguration.config_data_json_directory_path]:
            data_directory_path = os.path.join(directory, year)
            if not os.path.exists(data_directory_path):
                os.makedirs(data_directory_path)


def load_configuation(filename):

    if not os.path.exists(filename):
        raise FileNotFoundError(f"File {filename} not found.")

    # read the configuration from CONFIG_FILENAME using configparser module
    config = configparser.ConfigParser()
    config.read(filename)

    # Check that all sections start with "competition."
    for section in config.sections():
        if not section.startswith("competition."):
            raise ValueError(f"Invalid section name: {section}. All sections must start with 'competition.'")  # noqa: E501

        # Check that each section contains the name attribute
        for attribute in ["name", "start", "end"]:
            if not config.has_option(section, attribute):
                raise ValueError(f"Section {section} has no {attribute} attribute.")  # noqa: E501

    return config


def get_config_competitions(config):
    """
    Return a list of competitions from the configuration
    """

    competitions = []
    for section in config.sections():
        if section.startswith("competition."):
            competitions.append({"name": config[section]["name"],
                                 "year": config[section]["year"],
                                 "start": config[section]["start"],
                                 "end": config[section]["end"]})

    return competitions


def init_config(config_file_path):
    """
    Check if the directories exist and create them if needed
    """

    generate_directory_structure()
    config = load_configuation("config.ini")
    competitions = get_config_competitions(config)
    for competition in competitions:
        generate_directory_competitions_structure(competition)
    return config


if __name__ == "__main__":
    init_config(StaticConfiguration.config_file_path)
