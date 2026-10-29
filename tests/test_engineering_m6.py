import pytest
from asuna.sandbox import Sandbox


def test_E12_output_cap_and_literal_shell_arguments(runtime_work):
    work=runtime_work('limits');sandbox=Sandbox(work,config={'_host_sandbox':{'available':True}})
    text='literal; $(touch /tmp/ASUNA_HOST_ESCAPE) `echo nope`'
    result=sandbox.run(['python3','-c','import sys;print(sys.argv[1])',text])
    assert result['stdout'].strip()==text
    with pytest.raises(RuntimeError,match='OUTPUT_LIMIT'):
        sandbox.run(['python3','-c','import os;\nwhile True:os.write(1,b"x"*8192)'])
    assert sandbox.run(['python3','-c','print("still operational")'])['exit_code']==0


