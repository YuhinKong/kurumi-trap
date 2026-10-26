"""网络接口放在子进程，父进程可在超时后终止，包括内部多次HTTP请求。"""
import sys, json
def main():
    import akshare as ak
    name, kwargs = json.loads(sys.argv[1])
    result = getattr(ak,name)(**kwargs)
    print('RESULT_JSON:' + result.to_json(orient='records',date_format='iso',force_ascii=False))
if __name__ == '__main__':
    main()
