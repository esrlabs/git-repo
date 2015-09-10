import os
import unittest

import git_config

def fixture(*paths):
  """Return a path relative to test/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)

class GitConfigUnitTest(unittest.TestCase):
  """Tests the GitConfig class.
  """
  def setUp(self):
    """Create a GitConfig object using the test.gitconfig fixture.
    """
    config_fixture = fixture('test.gitconfig')
    self.config = git_config.GitConfig(config_fixture)

  def test_GetString_with_empty_config_values(self):
    """
    Test config entries with no value.

    [section]
        empty

    """
    val = self.config.GetString('section.empty')
    self.assertEqual(val, None)

  def test_GetString_with_true_value(self):
    """
    Test config entries with a string value.

    [section]
        nonempty = true

    """
    val = self.config.GetString('section.nonempty')
    self.assertEqual(val, 'true')

  def test_GetString_from_missing_file(self):
    """
    Test missing config file
    """
    config_fixture = fixture('not.present.gitconfig')
    config = git_config.GitConfig(config_fixture)
    val = config.GetString('empty')
    self.assertEqual(val, None)

if __name__ == '__main__':
  unittest.main()
